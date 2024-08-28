from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException
import requests
from flask import Flask, request, Response
import requests
import json
import uuid
from datetime import datetime, timezone
from gevent.pywsgi import WSGIServer
from gevent.lock import Semaphore
import time
import argparse
import os
import sys
import hashlib
from enum import Enum
import array


app = Flask(__name__)
selenium_lock = Semaphore()
cookies = {}
driver = {}

class ResponseFormat(Enum):
    CHAT = 1
    GENERATE = 2
    COMPLETION_AS_STRING = 3


def capture_and_redirect_browser_logs(driver):
    global debug_browser
    if not debug_browser: return
    logs = driver.get_log('browser')
    for entry in logs:
        print(f"Browser log: {entry['level']} - {entry['message']}", file=sys.stderr)


def login_to_venice(username, password):
    global cookies, driver
    print(f"Logging in to venice...")
    chrome_options = webdriver.ChromeOptions()
    if headless:
        chrome_options.add_argument("--headless")

    if args.debug_browser:
        chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    driver.get("https://venice.ai/sign-in")
    driver.find_element("id", "identifier").send_keys(username)
    wait = WebDriverWait(driver, selenium_timeout)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit'][contains(text(), 'Sign in')]")))
    button.click()

    password_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "password"))
    )

    password_input.send_keys(password)

    wait = WebDriverWait(driver, selenium_timeout)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit'][contains(text(), 'Sign in')]")))
    button.click()

    # Wait for the button to be clickable
    button = WebDriverWait(driver, selenium_timeout).until(
        EC.element_to_be_clickable((By.XPATH,
                                    "//button[.//p[contains(text(), 'Text Conversation')]]"))
    )

    # Wait for the account button to contain the "PRO" span (to make sure
    # venice realized we are a pro user)
    WebDriverWait(driver, selenium_timeout).until(
        EC.presence_of_element_located((By.XPATH,
                                        "//button[.//span[contains(text(), 'PRO')]]"))
    )
    print(f"Logged in as {username}")
    return driver

def inject_request_interceptor(driver, api_data_json):
    script = f"""
    window.streamComplete = false;
    window.receivedChunks = [];
    (function(original) {{
      const apiData = {api_data_json};
      window.fetch = async function() {{
        let url = arguments[0];
        let options = arguments[1];

        if (url.includes('/api/inference/chat') && options.method === 'POST') {{
          window.fetch = original;
          let body = JSON.parse(options.body);
          if ('requestId' in body) {{
            delete apiData.requestId;
          }}
          Object.assign(body, apiData);
          options.body = JSON.stringify(body);
          options.headers['Content-Length'] = new Blob([options.body]).size.toString();


          // Perform the fetch and get the response
          const response = await original.apply(this, arguments);
          const reader = response.body.getReader();

          // Set up a stream for the Python code to read
          window.responseStream = new ReadableStream({{
            start(controller) {{
              function push() {{
                reader.read().then(({{ done, value }}) => {{
                  if (done) {{
                    controller.close();
                    window.streamComplete = true;
                    return;
                  }}
                  window.receivedChunks.push(value);
                  controller.enqueue(value);
                  push();
                }});
              }}
              push();
            }}
          }});

          // Return a new response with our custom stream
          return new Response(window.responseStream, {{
            headers: response.headers,
            status: response.status,
            statusText: response.statusText
          }});
        }}

        return original.apply(this, arguments);
      }};
    }})(window.fetch);
    """
    driver.execute_script(script)

def generate_selenium_streamed_response(data, driver, response_format=ResponseFormat.CHAT):
    global timeout
    request_id = str(uuid.uuid4())[:8]
    model_id = data.get('model', 'llama-3.1-405b-akash-api')
    if ':latest' in model_id:
        model_id = model_id.split(':latest')[0]

    api_data = {
        "requestId": request_id,
        "modelId": model_id,
        "prompt": data['messages'],
        "systemPrompt": "",
        "conversationType": "text",
        "temperature": 0.8,
        "topP": 0.9
    }

    api_data_json = json.dumps(api_data)
    try:
        driver.get('https://venice.ai/chat')
        WebDriverWait(driver, selenium_timeout).until(
            EC.element_to_be_clickable((By.XPATH,
                                        "//button[.//p[contains(text(), 'Text Conversation')]]"))
        ).click()

        textarea = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//textarea[@placeholder='Ask a question...']"))
        )

        # just send space to enable the input box, we'll intercept the request
        # and replace it in flight (i.e. black magic)
        textarea.send_keys(" ")

        inject_request_interceptor(driver, api_data_json)

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and @aria-label='submit']"))
        ).click()



        start_time = datetime.now(timezone.utc)

        eval_count = 0
        last_data_time = time.time()
        while True:
            chunks = driver.execute_script("return window.receivedChunks.splice(0, window.receivedChunks.length);")
            buffer = ""
            for chunk in chunks:
                last_data_time = time.time()
                chunk_str = bytes(array.array('B', chunk)).decode('utf-8')
                buffer += chunk_str
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)  # Split at the first newline
                    if line:
                        try:
                            json_data = json.loads(line)
                            if json_data.get('kind') == 'content' and len(json_data.get('content', '')) > 0:
                                message = None
                                eval_count += 1

                                if response_format == ResponseFormat.CHAT:
                                    message = {
                                        "model": model_id,
                                        "created_at": datetime.utcnow().isoformat() + "Z",
                                        "message": {"role": "assistant", "content": json_data.get('content', '')},
                                        "done": False
                                    }
                                    yield f"{json.dumps(message)}\r\n"
                                elif response_format == ResponseFormat.GENERATE:
                                    message = {
                                        "model": model_id,
                                        "created_at": datetime.utcnow().isoformat() + "Z",
                                        "response": json_data.get('content', ''),
                                        "done": False
                                    }
                                    yield f"{json.dumps(message)}\r\n"
                                elif response_format == ResponseFormat.COMPLETION_AS_STRING:
                                    yield json_data.get('content', '')
                            elif len(json_data.get('content', '')) > 0:
                                print(f"Got an unknown message of kind {json_data.get('kind')}:\n{line}")
                        except json.JSONDecodeError:
                            print(f"Failed to parse line: {line}")

            if driver.execute_script("return window.streamComplete;"):
                break
            if time.time() - last_data_time > timeout:
                print(f"Timeout: No data received for {timeout} seconds. Exiting loop.")
                break
            time.sleep(0.1)

        capture_and_redirect_browser_logs(driver)

        if (response_format == ResponseFormat.CHAT) or (response_format == ResponseFormat.GENERATE):
            end_time = datetime.now(timezone.utc)
            duration = int((end_time - start_time).total_seconds() * 1e9)  # nanoseconds

            final_message = {
                "model": model_id,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "message": {"role": "assistant", "content": ""},
                "done_reason": "stop",
                "done": True,
                "total_duration": duration,
                "load_duration": duration,
                "prompt_eval_count": eval_count,
                "prompt_eval_duration": duration,
                "eval_count": eval_count,
                "eval_duration": duration
            }

            yield f"{json.dumps(final_message)}"
    except WebDriverException as e:
        print(f"Error occurred during chat: {e}")
        try:
            driver.quit()
        except WebDriverException as e:
            print(f"Error occurred while quitting WebDriver: {e}")

        driver = login_to_venice(username, password)
        if driver:
            yield from generate_selenium_streamed_response(data, driver, response_format)


def parse_json_request(request):
    content_type = request.headers.get('Content-Type')

    if content_type == 'application/json':
        return request.json
    elif content_type == 'text/plain; charset=utf-8':
        data = request.data.decode('utf-8')
        try:
          return json.loads(data)
        except json.JSONDecodeError:
          return None

@app.route('/api/chat', methods=['POST'])
def chat():
    global driver
    request_json = parse_json_request(request)
    if request_json is None :
            return Response("Invalid JSON data received", status=400, content_type='text/plain')
    with selenium_lock:
        return Response(generate_selenium_streamed_response(request_json, driver, response_format=ResponseFormat.CHAT), content_type='application/x-ndjson')

@app.route('/api/generate', methods=['POST'])
def generate():
    global driver
    request_json = parse_json_request(request)
    if request_json is None :
        return Response("Invalid JSON data received", status=400, content_type='text/plain')

    prompt = request_json.pop('prompt')

    if '[INST]' in prompt:
        inst_start = prompt.find('[INST]')
        inst_end = prompt.find('[/INST]')

        instructions = prompt[inst_start + 6:inst_end]
        response = prompt[inst_end + 7:]
        request_json["messages"] = [
            {
                "role": "user",
                "content": instructions.strip()
            },
            {
                "role": "assistant",
                "content": response.strip()
            }
        ]
    else:
        request_json["messages"] = [
            {
                "role": "user",
                "content": prompt
            }
        ]
    with selenium_lock:
        return Response(generate_selenium_streamed_response(request_json, driver, response_format=ResponseFormat.GENERATE), content_type='application/x-ndjson')

@app.route('/v1/chat/completions', methods=['POST'])
def openai_like_completion():
    request_json = parse_json_request(request)
    completion = ''.join(generate_selenium_streamed_response(request_json, driver, response_format=ResponseFormat.COMPLETION_AS_STRING))
    response_json = {
        "id": "chatcmpl-953",
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": request_json["model"],
        "system_fingerprint": "fp_ollama",
        "choices": [
            {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": completion
            },
            "finish_reason": "stop"
            }
        ]
        }
    return Response(json.dumps(response_json), mimetype='application/json')






@app.route('/api/version', methods=['GET'])
def version():
    return Response(json.dumps({"version":"0.3.6"}), content_type='application/json')

def get_mock_model(name, parameter_size):
    return {
      "name": name,
      "model": name,
      "modified_at": "2024-08-16T18:50:00.684933726+02:00",
      "size": 15628387458,
      "digest": hashlib.sha256(json.dumps({"name": name, "parameter_size": parameter_size}, sort_keys=True).encode("utf-8")).hexdigest(),
      "details": {
        "parent_model": "",
        "format": "gguf",
        "family": "llama",
        "families": [ "llama" ],
        "parameter_size": parameter_size,
        "quantization_level": "Q7_0"
      }
    }

@app.route('/api/tags', methods=['GET'])
def tags():
    tags_response = {
        "models": [
            get_mock_model("llama-3.1-405b-akash-api:latest", "405B"),
            get_mock_model("hermes-2-theta-web:latest", "8B"),
            get_mock_model("nous-hermes-8-web:latest", "8B")
        ]}
    return Response(json.dumps(tags_response), content_type='application/json')

@app.route('/api/show', methods=['POST'])
def mock_show():
    show_response = {
        "modelfile": "# Modelfile generated by \"ollama show\"\n# To build a new Modelfile based on this one, replace the FROM line with:\n# FROM llava:latest\n\nFROM /Users/matt/.ollama/models/blobs/sha256:200765e1283640ffbd013184bf496e261032fa75b99498a9613be4e94d63ad52\nTEMPLATE \"\"\"{{ .System }}\nUSER: {{ .Prompt }}\nASSISTANT: \"\"\"\nPARAMETER num_ctx 4096\nPARAMETER stop \"\u003c/s\u003e\"\nPARAMETER stop \"USER:\"\nPARAMETER stop \"ASSISTANT:\"",
        "parameters": "num_keep                       24\nstop                           \"<|start_header_id|>\"\nstop                           \"<|end_header_id|>\"\nstop                           \"<|eot_id|>\"",
        "template": "{{ if .System }}<|start_header_id|>system<|end_header_id|>\n\n{{ .System }}<|eot_id|>{{ end }}{{ if .Prompt }}<|start_header_id|>user<|end_header_id|>\n\n{{ .Prompt }}<|eot_id|>{{ end }}<|start_header_id|>assistant<|end_header_id|>\n\n{{ .Response }}<|eot_id|>",
        "details": {
            "parent_model": "",
            "format": "gguf",
            "family": "llama",
            "families": [
            "llama"
            ],
            "parameter_size": "8.0B",
            "quantization_level": "Q4_0"
        },
        "model_info": {
            "general.architecture": "llama",
            "general.file_type": 2,
            "general.parameter_count": 8030261248,
            "general.quantization_version": 2,
            "llama.attention.head_count": 32,
            "llama.attention.head_count_kv": 8,
            "llama.attention.layer_norm_rms_epsilon": 0.00001,
            "llama.block_count": 32,
            "llama.context_length": 8192,
            "llama.embedding_length": 4096,
            "llama.feed_forward_length": 14336,
            "llama.rope.dimension_count": 128,
            "llama.rope.freq_base": 500000,
            "llama.vocab_size": 128256,
            "tokenizer.ggml.bos_token_id": 128000,
            "tokenizer.ggml.eos_token_id": 128009,
            "tokenizer.ggml.merges": [],            # populates if `verbose=true`
            "tokenizer.ggml.model": "gpt2",
            "tokenizer.ggml.pre": "llama-bpe",
            "tokenizer.ggml.token_type": [],        # populates if `verbose=true`
            "tokenizer.ggml.tokens": []             # populates if `verbose=true`
        }
        }
    return show_response

## main code

parser = argparse.ArgumentParser(description='Ollama-like API for venice.ai')

# Mandatory arguments (USERNAME and PASSWORD)
parser.add_argument('--username', type=str, required=False, help='Venice username')
parser.add_argument('--password', type=str, required=False, help='Venice password')

# Optional arguments with defaults
parser.add_argument('--host', type=str, default='127.0.0.1', help='Local host address')
parser.add_argument('--port', type=int, default=9999, help='Server port')
parser.add_argument('--timeout', type=int, default=20, help='Timeout for generating tokens from Venice (seconds)')
parser.add_argument('--selenium-timeout', type=int, default=60, help='Selenium timeout (seconds)')
parser.add_argument('--headless', action='store_true', default=True, help='Run Selenium in headless mode')
parser.add_argument('--no-headless', action='store_false', dest='headless', help='Disable headless mode and run with a visible browser window')
parser.add_argument('--debug-browser', action='store_true', default=False, help='Enable browser debugging logs')

args = parser.parse_args()

# Set username and password from environment variables if not provided
username = args.username or os.getenv('VENICE_USERNAME')
password = args.password or os.getenv('VENICE_PASSWORD')

if not username or not password:
    print("Both username and password for venice are required. Set using command line arguments or VENICE_USERNAME and VENICE_PASSWORD environment variables", file=sys.stderr)
    sys.exit(1)

timeout=args.timeout
selenium_timeout=args.selenium_timeout
headless = args.headless
debug_browser= args.debug_browser

driver = login_to_venice(username, password)
print(f"Starting server at port {args.host}:{args.port}")
http_server = WSGIServer((args.host, args.port), app)
http_server.serve_forever()
