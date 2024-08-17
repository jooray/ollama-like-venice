from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
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


app = Flask(__name__)
cookies_lock = Semaphore()
cookies = {}

def login_to_venice(username, password):
    global cookies
    print(f"Logging in to venice as {username}")
    # initialize the Chrome driver
    chrome_options = webdriver.ChromeOptions()
    if headless:
        chrome_options.add_argument("--headless")

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
    cookies = {cookie['name']: cookie['value'] for cookie in driver.get_cookies()}
    driver.quit()
    print("Login successful")
    return cookies

def generate_streamed_response(data, chat_format=True):
    # Generate unique IDs
    unique_id = str(uuid.uuid4())[:23].replace('-', '_')
    request_id = str(uuid.uuid4())[:8]

    # Extract model_id from the incoming request data
    model_id = data.get('model', 'llama-3.1-405b-akash-api')
    if ':latest' in model_id:
        model_id = model_id.split(':latest')[0]


    # Set up the headers and JSON data for the POST request
    headers = {
        'Content-Type': 'application/json',
        'Connection': 'close', # if venice discovers we are using scripts,
                               # this might be the culprint, this is not standard
        'Referer': f'https://venice.ai/chat/{unique_id}'
    }

    api_data = {
        "requestId": request_id,
        "modelId": model_id,
        "prompt": data['messages'],
        "systemPrompt": "",
        "conversationType": "text",
        "temperature": 0.8,
        "topP": 0.9
    }

    print(f"Sending request to venice with content: {api_data}")

    url = 'https://venice.ai/api/inference/chat'

    # Send the POST request using the cookies extracted from Selenium
    session = requests.Session()
    start_time = datetime.now(timezone.utc)

    try:
        with cookies_lock:
            global cookies
            global timeout

            should_retry = True
            delay = 1
            max_delay = 16
            response = None
            while should_retry:
                should_retry = False
                response = session.post(url, headers=headers, data=json.dumps(api_data), cookies=cookies, stream=True, timeout=(None, timeout))

                if response.status_code == 429:
                    print("Got too many requests, trying a new login...")
                    time.sleep(delay)
                    delay = delay * 2
                    if delay <= max_delay:
                        should_retry = True
                    cookies = login_to_venice(username, password)

            if response.status_code != 200:
                print(f"Error: {response.status_code}")
                print(f"Reason: {response.reason}")
                raise Exception(f"Request failed with status code {response.status_code}")

            cookies.update(response.cookies)

        eval_count = 0

        for line in response.iter_lines():
            if line:
                json_data = json.loads(line.decode('utf-8'))
                kind = json_data.get('kind')

                if kind == 'content':
                    eval_count += 1
                    message = None
                    if chat_format:
                        message = {
                            "model": model_id,
                            "created_at": datetime.utcnow().isoformat() + "Z",
                            "message": {"role": "assistant", "content": json_data.get('content', '')},
                            "done": False
                        }
                    else:
                        message = {
                            "model": model_id,
                            "created_at": datetime.utcnow().isoformat() + "Z",
                            "response": json_data.get('content', ''),
                            "done": False
                        }

                    yield f"{json.dumps(message)}\r\n"
                else:
                    print(f"Got a message of kind {kind}:\n{line}")
    except requests.Timeout:
        print("Timeout while reading...")
        return

    # Once the stream is finished, calculate the durations and prepare the final message
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

    response.close()

    yield f"{json.dumps(final_message)}\r\n"

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
    request_json = parse_json_request(request)
    if request_json is None :
            return Response("Invalid JSON data received", status=400, content_type='text/plain')
    return Response(generate_streamed_response(request_json, chat_format=True), content_type='application/x-ndjson')

@app.route('/api/generate', methods=['POST'])
def generate():
    request_json = parse_json_request(request)
    if request_json is None :
        return Response("Invalid JSON data received", status=400, content_type='text/plain')

    request_json["messages"] = [
        {
            "role": "user",
            "content": f"This will be a completion request. Act as an AI that continues with the request, not as a chatbot. After the prompt ends, just continue with tokens that would follow. Instructions for you are in [INST]...[/INST]{request_json['prompt']}"
        }
    ]
    return Response(generate_streamed_response(request_json, chat_format=False), content_type='application/x-ndjson')

@app.route('/api/version', methods=['GET'])
def version():
    return Response(json.dumps({"version":"0.2.5"}), content_type='application/json')

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
            get_mock_model("dogge-llama-3-70b:latest", "70B")
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

parser = argparse.ArgumentParser(description='Ollama-like API for venice.ai')

# Mandatory arguments (USERNAME and PASSWORD)
parser.add_argument('--username', type=str, required=False, help='Venice username')
parser.add_argument('--password', type=str, required=False, help='Venice password')

# Optional arguments with defaults
parser.add_argument('--host', type=str, default='127.0.0.1', help='Local host address')
parser.add_argument('--port', type=int, default=9999, help='Server port')
parser.add_argument('--timeout', type=int, default=42, help='Timeout for generating tokens from Venice (seconds)')
parser.add_argument('--selenium-timeout', type=int, default=60, help='Selenium timeout (seconds)')
parser.add_argument('--headless', action='store_true', default=True, help='Run Selenium in headless mode')

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

cookies = login_to_venice(username, password)
print(f"Starting server at port {args.host}:{args.port}")
http_server = WSGIServer((args.host, args.port), app)
http_server.serve_forever()
