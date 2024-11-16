from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
from selenium.webdriver.common.by import By
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import TimeoutException
from flask import Flask, request, Response
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
driver = {}

class ResponseFormat(Enum):
    CHAT = 1
    GENERATE = 2
    COMPLETION_AS_STRING = 3
    CHAT_NON_STREAMED = 4


def capture_and_redirect_browser_logs(driver):
    global debug_browser
    if not debug_browser: return
    logs = driver.get_log('browser')
    for entry in logs:
        print(f"Browser log: {entry['level']} - {entry['message']}", file=sys.stderr)


def get_webdriver(headless=True, debug_browser=False, docker=False):
    chrome_options = webdriver.ChromeOptions()
    if headless:
        chrome_options.add_argument("--headless")
    if debug_browser:
        chrome_options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    if docker:
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

    if args.seed:
        chrome_options.add_argument("--disable-features=ChromeAppsDeprecation")

    chrome_options.page_load_strategy = 'eager'
    # Check if system-wide chromedriver exists
    system_chromedriver = "/usr/bin/chromedriver"
    if os.path.exists(system_chromedriver) and os.access(system_chromedriver, os.X_OK):
        print(f"Using system-wide chromedriver: {system_chromedriver}")
        service = Service(system_chromedriver)

        # Try to use Chromium first
        try:
            chrome_options.binary_location = "/usr/bin/chromium"
            driver = webdriver.Chrome(service=service, options=chrome_options)
            print("Using Chromium")
            return driver
        except WebDriverException as e:
            print(f"Chromium initialization failed: {e}")

        # If Chromium fails, try Chrome
        try:
            chrome_options.binary_location = ""
            driver = webdriver.Chrome(service=service, options=chrome_options)
            print("Using Google Chrome")
            return driver
        except WebDriverException as e:
            print(f"Chrome initialization failed: {e}")
    else:
        # Use ChromeDriverManager to install

        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            return driver
        except WebDriverException as e:
            print(f"Chrome not found ({e}), trying Chromium")


        try:
            driver = webdriver.Chrome(service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()), options=chrome_options)
            return driver
        except WebDriverException as e:
            print(f"Chromium error occurred: {e}")

    raise Exception("Neither Chrome nor Chromium could be initialized. Please make sure one of them is installed.")

def ensure_logged_in(driver):
    max_attempts = 3
    attempt = 0

    # Wait for the account button to contain the "PRO" span (to make sure
    # venice realized we are a pro user)
    while attempt < max_attempts:
        try:
            WebDriverWait(driver, selenium_timeout).until(
            EC.element_to_be_clickable((By.XPATH,
                                    "//button[.//p[contains(text(), 'Text Conversation')]]"))
            )

            if args.ensure_pro:
                WebDriverWait(driver, selenium_timeout).until(
                    EC.presence_of_element_located((By.XPATH,
                                                    "//button[.//span[contains(text(), 'PRO')]]"))
                )
            break
        except TimeoutException:
            if attempt < max_attempts - 1:
                print(f"PRO span not found. Refreshing... (Attempt {attempt + 1}/{max_attempts})")
                driver.refresh()
            attempt += 1

    if attempt == max_attempts:
        raise TimeoutException("PRO span not found after maximum refresh attempts")

def login_to_venice_with_username(username, password):
    global driver, args
    print(f"Logging in to venice with username and password...")
    driver = get_webdriver(headless=args.headless, debug_browser=args.debug_browser, docker=args.docker)

    driver.get("https://venice.ai/sign-in")
    wait = WebDriverWait(driver, selenium_timeout)

    email_field = wait.until(EC.visibility_of_element_located((By.ID, "identifier")))
    email_field.send_keys(username)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit'][contains(text(), 'Sign in')]")))
    button.click()

    password_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "password"))
    )

    password_input.send_keys(password)

    wait = WebDriverWait(driver, selenium_timeout)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit'][contains(text(), 'Sign in')]")))
    button.click()

    ensure_logged_in(driver)

    print(f"Logged in as {username}")
    return driver

def inject_web3_provider(driver, seed):
    script = """
    (function injectWeb3Provider() {
    const script = document.createElement('script');
    script.textContent = `
        (function() {
            function loadScript(url) {
                return new Promise((resolve, reject) => {
                    const script = document.createElement('script');
                    script.src = url;
                    script.onload = resolve;
                    script.onerror = reject;
                    document.head.appendChild(script);
                });
            }

            async function loadDependencies() {
                await loadScript('https://cdnjs.cloudflare.com/ajax/libs/ethers/5.7.2/ethers.umd.min.js');
                await loadScript('https://cdnjs.cloudflare.com/ajax/libs/web3/1.8.2/web3.min.js');
            }

            function createProvider(wallet) {
                const provider = {
                    isMetaMask: true,
                    _metamask: {
                        isUnlocked: () => Promise.resolve(true),
                        requestBatch: () => Promise.resolve(),
                        isApproved: () => Promise.resolve(true),
                    },
                    selectedAddress: wallet.address,
                    networkVersion: '1', // Arbitrum One: 42161
                    chainId: '0x1', // Arbitrum One: 0xa4b1
                    isConnected: () => true,
                    subscriptions: new Map(),
                    request: async ({ method, params }) => {
                        console.log('Request received:', method, params);
                        return new Promise((resolve, reject) => {
                            switch (method) {
                                case 'eth_requestAccounts':
                                case 'eth_accounts':
                                    resolve([wallet.address]);
                                case 'personal_sign':
                                    message = params[0];
                                    if (message.startsWith('0x')) {
                                            message = ethers.utils.toUtf8String(message);
                                    }

                                    const address = params[1];
                                    if (address.toLowerCase() !== wallet.address.toLowerCase()) {
                                        console.log('Address is wrong');
                                        reject(new Error('Address mismatch'));
                                    } else {
                                        wallet.signMessage(message)
                                            .then(signature => {
                                                console.log('Returning signature');
                                                resolve(signature);
                                            })
                                            .catch(error => {
                                                console.error('Error signing message:', error);
                                                reject(error);
                                            });
                                    }
                                    break;
                                case 'eth_sign':
                                    const messageToSign = ethers.utils.arrayify(params[1]);
                                    const addressForEthSign = params[0];
                                    if (addressForEthSign.toLowerCase() !== wallet.address.toLowerCase()) {
                                        reject(new Error('Address mismatch'));
                                    } else {
                                        return wallet.signMessage(messageToSign);
                                    }
                                    break;
                                case 'eth_chainId':
                                    resolve('0x1');
                                    break;
                                case 'net_version':
                                    resolve('1');
                                    break;
                                case 'wallet_switchEthereumChain':
                                    resolve();
                                    break;
                                default:
                                    reject(new Error(\`Unsupported web3 method: \${method}\`));
                            }
                        });
                    },
                    setMaxListeners: function(n) {
                      console.log('setMaxListeners called with:', n);
                    },
                    bzz: undefined,
                    removeListener: function(eventName, listener) {
                       console.log('removeListener called for:', eventName);
                    },
                    on: (eventName, callback) => {
                        const subscriptionId = \`sub_${Math.random().toString(36).substring(2, 15)}\`;
                        console.log('Setting up provider event listener for:', eventName, 'with subscriptionId:', subscriptionId);
                        switch (eventName) {
                            case 'accountsChanged':
                                provider.subscriptions.set(subscriptionId, { callback });
                                setTimeout(() => callback([wallet.address]), 500);
                                break;

                            case 'connect':
                                console.log('Connected to the network');
                                provider.subscriptions.set(subscriptionId, { callback });
                                setTimeout(() => callback({ chainId: '0x1' }), 500);
                                break;

                            case 'message':
                            case 'disconnect':
                            case 'error':
                                provider.subscriptions.set(subscriptionId, { callback });
                                break;

                            case 'chainChanged':
                                provider.subscriptions.set(subscriptionId, { callback });
                                setTimeout(() => callback({ chainId: '0x01' }), 500);
                                break;

                            default:
                                console.log('Unsupported web3 event:', eventName);
                                reject(new Error(\`Unsupported web3 event: \${eventName}\`));
                        }

                        console.log(\`Called provider.on(\${eventName}, \${callback})\`);
                    },
                    removeListener: () => {},
                };

                // Mimic MetaMask's extension behavior
                provider.request.toString = () => 'function request() { [native code] }';
                Object.setPrototypeOf(provider, EventTarget.prototype);

                const eip6963_metamask_provider = {
                    info: {
                        name: "MetaMask",
                        uuid: "04c4cfd0-60b3-49fb-8f11-e181fa32b912",
                        rdns: "io.metamask",
                        icon: ""
                    },
                    provider: provider
                };

                function announceMetamaskWalletProvider() {
                      console.log('announceMetamaskWalletProvider called');
                      console.log('event detail:', eip6963_metamask_provider);

                    window.dispatchEvent(new CustomEvent("eip6963:announceProvider", {
                        detail: eip6963_metamask_provider,
                        bubbles: true,
                        cancelable: false
                    }));
                }
                setTimeout(announceMetamaskWalletProvider, 100);
                window.addEventListener("eip6963:requestProvider", announceMetamaskWalletProvider);

                //return provider;

                // DEBUG ON
                try {
                    return new Proxy(provider, {
                        get(target, prop) {
                            try {
                                const value = target[prop];
                                const stack = new Error().stack;
                                console.log('Accessing property:', String(prop));
                                console.log('Stack trace:', stack);


                                if (typeof value === 'function') {
                                    return function(...args) {
                                        try {
                                            console.log('Calling method:', String(prop), args);
                                            return value.apply(target, args);
                                        } catch (error) {
                                            console.error('Error calling method:', String(prop), error);
                                            return undefined;
                                        }
                                    };
                                }

                                return value;
                            } catch (error) {
                                console.error('Error accessing property:', String(prop), error);
                                return undefined;
                            }
                        },
                        set(target, prop, value) {
                            try {
                                console.log('Setting property:', String(prop), value);
                                target[prop] = value;
                                return true;
                            } catch (error) {
                                console.error('Error setting property:', String(prop), error);
                                return false;
                            }
                        }
                    });
                } catch (error) {
                    console.error('Error creating proxy:', error);
                    return provider;
                }

            // DEBUG OFF
            }

            console.log('Loading dependencies')
            loadDependencies().then(() => {
                const seed = '{seed}';
                const hdNode = ethers.utils.HDNode.fromMnemonic(seed);
                const wallet = new ethers.Wallet(hdNode.derivePath("m/44'/60'/0'/0/0"));

                console.log('Creating provider')

                const provider = createProvider(wallet);

                //window.web3 = new Web3(provider);

                // Dispatch event to notify that the provider is ready
                //window.dispatchEvent(new Event('ethereum#initialized'));

                // Mimic content script injection
                //const metaMaskScript = document.createElement('script');
                //metaMaskScript.setAttribute('data-extension-id', 'nkbihfbeogaeaoehlefnkodbefgpgknn'); // MetaMask's extension ID
                //document.head.appendChild(metaMaskScript);

                console.log('Web3 provider injected successfully');
            });
        })();
    `;
    document.documentElement.appendChild(script);
    script.remove();
})();

    """.replace('{seed}', seed)
    driver.execute_script(script)



def element_and_shadow_root_exist(driver, selector):
    script = f"""
        const el = {selector};
        return el && el.shadowRoot;
    """
    return driver.execute_script(script)

def login_to_venice_with_seed(seed):
    global driver, args
    print(f"Logging in to venice with seed...")
    driver = get_webdriver(headless=args.headless, debug_browser=args.debug_browser, docker=args.docker)

    driver.get("about:blank")
    inject_web3_provider(driver, seed)
    driver.get("https://venice.ai/sign-in")
    print("Injecting web3 provider")
    inject_web3_provider(driver, seed)

    print("Waiting to click on Wallet Connect")
    wait = WebDriverWait(driver, selenium_timeout)
    button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Wallet Connect']")))
    button.click()

    print("Clicked")
    wait.until(lambda driver: driver.execute_script(
        "return document.querySelector('w3m-modal').classList.contains('open');"))

    selectors = [
        "document.querySelector('w3m-modal')",
        ".querySelector('w3m-router')",
        ".querySelector('w3m-connecting-siwe-view')",
        ".querySelectorAll('wui-button')[1]"
    ]

    current_selector = selectors[0]
    for next_selector in selectors[1:]:
        WebDriverWait(driver, selenium_timeout).until(
            lambda x: element_and_shadow_root_exist(x, current_selector)
        )
        current_selector += ".shadowRoot" + next_selector

    sign_button_selector = current_selector
    js_is_clickable = f"""
        const button = {sign_button_selector};
        return button && !button.disabled;
    """
    WebDriverWait(driver, selenium_timeout).until(lambda x: x.execute_script(js_is_clickable))

    js_click = f"""
        const button = {sign_button_selector};
        button.click();
    """

    driver.execute_script(js_click)

    ensure_logged_in(driver)

    print(f"Logged in with seed")
    return driver


def login_to_venice():
    if (username is not None and password is not None and len(username)>0):
        return login_to_venice_with_username(username, password)
    elif (seed is not None):
        return login_to_venice_with_seed(seed)
    else:
        print("No username and password, nor seed provided")
        sys.exit(1)

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

def presence_of_either_element_located(locators):
    def _predicate(driver):
        for locator in locators:
            try:
                element = driver.find_element(*locator)
                if element.is_displayed():
                    return element
            except:
                pass
        return False
    return _predicate

def generate_selenium_streamed_response(data, driver, response_format=ResponseFormat.CHAT):
    global timeout
    request_id = str(uuid.uuid4())[:8]
    model_id = data.get('model', 'llama-3.1-405b-akash-api')
    request_model_id = model_id
    if ':latest' in request_model_id:
        request_model_id = request_model_id.split(':latest')[0]

    api_data = {
        "requestId": request_id,
        "modelId": request_model_id,
        "prompt": data['messages'],
        "systemPrompt": "",
        "conversationType": "text",
        "temperature": 0.8,
        "topP": 0.9
    }

    api_data_json = json.dumps(api_data)
    try:
        if not driver.current_url.startswith('https://venice.ai/chat'):
            driver.get('https://venice.ai/chat')

        element = WebDriverWait(driver, selenium_timeout).until(
            presence_of_either_element_located((
                (By.XPATH, "//button[.//p[contains(text(), 'Text Conversation')]]"),
                (By.XPATH, "//textarea[contains(@placeholder, 'Ask a question')]")
            ))
        )

        if element.tag_name == 'button':
            element.click()
            element = WebDriverWait(driver, selenium_timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//textarea[contains(@placeholder, 'Ask a question')]"))
            )
        WebDriverWait(driver, selenium_timeout).until(
            lambda d: element.is_displayed() and element.is_enabled()
        )

        element.click()
        element.send_keys(" ")

        current_url = driver.current_url

        # If we are on the main chat page, the button will navigate us to a different url first
        if current_url == 'https://venice.ai/chat':
            WebDriverWait(driver, selenium_timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and @aria-label='submit']"))
            ).click()
            WebDriverWait(driver, selenium_timeout).until(EC.url_changes(current_url))
            element = WebDriverWait(driver, selenium_timeout).until(
                EC.element_to_be_clickable((By.XPATH, "//textarea[contains(@placeholder, 'Ask a question')]"))
            )
            WebDriverWait(driver, selenium_timeout).until(
                lambda d: element.is_displayed() and element.is_enabled()
            )

            element.click()
            element.send_keys(" ")


        inject_request_interceptor(driver, api_data_json)

        button = WebDriverWait(driver, selenium_timeout).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and @aria-label='submit']"))
        )

        button.click()

        start_time = datetime.now(timezone.utc)

        eval_count = 0
        last_data_time = time.time()
        streamed_content = ""
        while True:
            chunks = driver.execute_script("""
                if (typeof window.receivedChunks !== 'undefined' && window.receivedChunks !== null) {
                    return window.receivedChunks.splice(0, window.receivedChunks.length);
                } else {
                    return [];
                }
            """)
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
                                elif response_format == ResponseFormat.CHAT_NON_STREAMED:
                                    streamed_content += json_data.get('content', '')
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

        if (response_format == ResponseFormat.CHAT) or (response_format == ResponseFormat.GENERATE) or (response_format == ResponseFormat.CHAT_NON_STREAMED):
            end_time = datetime.now(timezone.utc)
            duration = int((end_time - start_time).total_seconds() * 1e9)  # nanoseconds

            final_message = {
                "model": model_id,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "message": {"role": "assistant", "content": streamed_content},
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

        driver = login_to_venice()
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

    response_format = ResponseFormat.CHAT
    content_type = 'application/x-ndjson'

    if 'stream' in request_json and request_json['stream'] == False:
        response_format = ResponseFormat.CHAT_NON_STREAMED
        content_type = 'application/json; charset=utf-8'

    with selenium_lock:
        return Response(generate_selenium_streamed_response(request_json, driver, response_format=response_format), content_type=content_type)

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
            get_mock_model("dolphin-2.9.2-qwen2-72b:latest","72B"),
            get_mock_model("llama-3.2-3b-akash:latest", "3B"),
            get_mock_model("llama-3.1-nemotron-70b:latest", "70B"),
            get_mock_model("nous-theta-web:latest", "8B"),
            get_mock_model("nous-hermes3a-web:latest", "8B")
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

parser.add_argument('--username', type=str, required=False, help='Venice username')
parser.add_argument('--password', type=str, required=False, help='Venice password')

# Optional arguments with defaults
parser.add_argument('--host', type=str, default='127.0.0.1', help='Local host address')
parser.add_argument('--port', type=int, default=9999, help='Server port')
parser.add_argument('--timeout', type=int, default=20, help='Timeout for generating tokens from Venice (seconds)')
parser.add_argument('--selenium-timeout', type=int, default=20, help='Selenium timeout (seconds)')
parser.add_argument('--headless', action='store_true', default=True, help='Run Selenium in headless mode')
parser.add_argument('--no-headless', action='store_false', dest='headless', help='Disable headless mode and run with a visible browser window')
parser.add_argument('--debug-browser', action='store_true', default=False, help='Enable browser debugging logs')
parser.add_argument('--docker', action='store_true', default=False, help='Do not run Chrome sandbox (required for docker)')
parser.add_argument('--seed', type=str, required=False, help='Seed to log in with WalletConnect')
parser.add_argument('--ensure-pro', action='store_true', default=False, help='Ensure that Venice recognized the user has a pro account')

args = parser.parse_args()

# Set username and password or seed from environment variables if not provided
username = args.username or os.getenv('VENICE_USERNAME')
password = args.password or os.getenv('VENICE_PASSWORD')
seed = args.seed or os.getenv('VENICE_SEED')

if (not seed) and (not username or not password):
    print("Either seed or both username and password for venice are required. Set using command line arguments or environment variables - VENICE_SEED or VENICE_USERNAME and VENICE_PASSWORD", file=sys.stderr)
    sys.exit(1)

timeout=args.timeout
selenium_timeout=args.selenium_timeout
debug_browser = args.debug_browser

driver = login_to_venice()
print(f"Starting server at port {args.host}:{args.port}")
http_server = WSGIServer((args.host, args.port), app)
http_server.serve_forever()
