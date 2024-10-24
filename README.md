# Ollama-like API for Venice

- [Introduction](#introduction)
- [Installation](#installation)
- [Installation through Docker](#installation-through-docker)
- [Usage](#usage)
- [Setting up Open-WebUI](#setting-up-open-webui)
- [Setting up continue.dev](#setting-up-continuedev)
- [Contributing](#contributing)

## Introduction

This project simulates the Ollama API using Venice.ai's text generation capabilities, allowing users to access a lifetime Pro account without token fees, usage costs, or subscriptions. The project uses Selenium automation framework to interact with Venice in a clever way, making it suitable for personal inference and integration with IDEs and LLM front-ends.

## Venice Pro accounts for sale

If you would become a lifetime Pro user on Venice, head over to the 
[original crowdfunding page](https://pay.cypherpunk.today/apps/26zEBNn6FGAkzvVVuDMz3SXrKJLU/crowdfund), the pro accounts are still on sale.

Please note that currently they are seed-based (not e-mail/password), but they should work with this code.

## Installation

To install the project, follow these steps:

Make sure pip and python commands are Python 3.11 or higher. If you are not sure, run this command:

```bash
pip --version
python --version
```

Especially note if pip and python are different python versions, that might cause problems.

If they are lower version, you might try calling a command with version (python3.11, pip3.11 or python3 and pip3)

Navigate to the project directory using `cd ollama-like-venice`

Start by first creating and activating a Python virtual environment (optional but recommended):

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the required dependencies

```bash
pip install -r requirements.txt
```

## Installation through Docker

If you would rather install this through Docker, follow these steps:

```bash
docker build -t ollama-like-api-for-venice .
docker run -p 9999:9999 -e VENICE_USERNAME="USERNAME" -e VENICE_PASSWORD="PASSWORD" ollama-like-api-for-venice
```

Note that docker support is currently beta.

## Usage

First make sure that the virtual environment is activated by running `source .venv/bin/activate` in the project's directory.

Then set the environment variables, run the following commands in your terminal:

```bash
export VENICE_USERNAME="your-username"
export VENICE_PASSWORD="your-password"
```

Replace "your-username" and "your-password" with your actual Venice credentials.

If you have a life time pro account based on MOR token in your wallet, you can login using seed instead of username and password:

```bash
export VENICE_SEED="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
```

Run the server using `python ollama_like_server.py`

If you have a pro account, I recommend adding --ensure-pro flag, sometimes the pro account is not recognized and thus you don't have 
access to better models.

If you need to set additional options, see the options:

```
# python ollama_like_server.py --help
usage: ollama_like_server.py [-h] [--username USERNAME] [--password PASSWORD]
                             [--host HOST] [--port PORT] [--timeout TIMEOUT]
                             [--selenium-timeout SELENIUM_TIMEOUT]
                             [--headless] [--no-headless] [--debug-browser]
                             [--docker] [--seed SEED] [--ensure-pro]

Ollama-like API for venice.ai

options:
  -h, --help            show this help message and exit
  --username USERNAME   Venice username
  --password PASSWORD   Venice password
  --host HOST           Local host address
  --port PORT           Server port
  --timeout TIMEOUT     Timeout for generating tokens from Venice (seconds)
  --selenium-timeout SELENIUM_TIMEOUT
                        Selenium timeout (seconds)
  --headless            Run Selenium in headless mode
  --no-headless         Disable headless mode and run with a visible browser
                        window
  --debug-browser       Enable browser debugging logs
  --docker              Do not run Chrome sandbox (required for docker)
  --seed SEED           Seed to log in with WalletConnect
  --ensure-pro          Ensure that Venice recognized the user has a pro
                        account
```

## Troubleshooting

### WebDriver errors - check if Chrome is installed and working

If you get WebDriver errors, first make sure that you can run the Chrome binary from the command line.

Replace `/path/to/your/google-chrome` with your path to Chrome.

```bash
/path/to/your/google-chrome --headless --disable-gpu --dump-dom https://bitcoin.org/ | head -n 20 | grep "Bitcoin"
```

The output should be something like:
```html
<title>Bitcoin - Open source P2P money</title>
<meta name="description" content="Bitcoin is an innovative payment network and a new kind of money. Find all you need to know and get started with Bitcoin on bitcoin.org.">
```

If it does not work, use your operating system's package manager to install Chrome and all the required libraries.

### Can't login to venice

Make sure your password does not contain special characters. If you do, change it to password containing letters and numbers only - it can be long. I don't know why, but sometimes Selenium does not type these characters correctly.

Also you can try running ollama-live-venice with `--no-headless` flag to see what is happening in the Chrome window.

## Setting up Open-WebUI

Now you can use the provided API with [Open-WebUI](https://openwebui.com/). You can install it [according to the instructions](https://docs.openwebui.com/getting-started/), but I think this is simpler and works better:

### Installation

```bash
mkdir open-webui && cd open-webui
python -m venv venv
source venv/bin/activate
pip install open-webui
```

### Running

```bash
cd open-webui
source venv/bin/activate
ENABLE_RAG_WEB_SEARCH=true RAG_WEB_SEARCH_ENGINE=duckduckgo OLLAMA_BASE_URL="http://127.0.0.1:9999" open-webui serve --port 8082
```

Now open-webui should listen on http://127.0.0.1:8082/, visit it through the browser.

If you run local ollama, you can set the URL like this:

```bash
cd open-webui
source venv/bin/activate
ENABLE_RAG_WEB_SEARCH=true RAG_WEB_SEARCH_ENGINE=duckduckgo OLLAMA_BASE_URLS="http://127.0.0.1:9999;http://127.0.0.1:11434" open-webui serve --port 8082
```


### Setting up venice through ollama-like proxy through web interface

I recommend setting the ollama URLs usng the method above, but you can also try using the web interface - it does not always persist restarts though.

After login to the Open-WebUI interface, click on your account (top right icon), then click on Admin Panel, choose the Settings tab, go to Connections.
Under the Ollama API either change the URL (if you don't run local Ollama), or
click "+" to add new entry and type in http://127.0.0.1:9999 (adjust the port
to match your local server configuration, 9999 is just default). If you set it through OLLAMA_BASE_URL above, the it might be already set correctly.

**Note**: If it does not work, make sure you put http://127.0.0.1:9999 and
**not** localhost, the library used by Open-WebUI sometimes has trouble with
resolving, especially if you have both ipv4 and ipv6 host entries for localhost.
Also, make sure you are using http, not https.

Then click on the arrows icon, which will verify the connection. If everything is ok, you should see the new models under new chat - the models are "llama-3.1-405b-akash-api", "dolphin-2.9.2-qwen2-72b", "llama-3.2-3b-akash", "llama-3.1-nemotron-70b", "nous-theta-web"
"
The *-web models have access to web search, llama-3.1-405b is the currently best open model.
Dolphin is the most uncensored model. Nemotron is a chain of thought model.

Note that you can also access web through "#" command in open-webui prompt, in this case web search is faciliated by open-webui, not venice.

## Setting up continue.dev

To use [continue.dev](https://continue.dev/) to help with your web development 
needs (or writing README-s like this one😅), install the extension into your Visual Studio Code or JetBrains-based IDE (I haven't tested JetBrains).

Then press the Continue button in the status bar and click on "Configure autocomplete options". An editor will appear. Add the models to models array,
for example this is a complete configuration:

```json
{
  "models": [
    {
      "title": "venice llama3.1-405b",
      "provider": "ollama",
      "apiBase": "http://127.0.0.1:9999",
      "model": "llama-3.1-405b-akash-api"
    },
    {
      "title": "venice dolphin-2.9.2-qwen2-72b",
      "provider": "ollama",
      "apiBase": "http://127.0.0.1:9999",
      "model": "dolphin-2.9.2-qwen2-72b"
    },
    {
      "title": "venice llama-3.2-3b-akash",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "llama-3.2-3b-akash"
    },
    {
      "title": "venice llama-3.1-nemotron-70b",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "llama-3.1-nemotron-70b"
    },
    {
      "title": "venice nous-theta-web",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "nous-theta-web"
    }
  ],
  "tabAutocompleteModel": {
    "title": "Starcoder",
    "provider": "ollama",
    "model": "starcoder2:3b"
  },
  "embeddingsProvider": {
    "provider": "ollama",
    "model": "nomic-embed-text"
  },
  "allowAnonymousTelemetry": false,
  "docs": []
}
```

I recommend installing also ollama and running the starcoder2 model locally.
For search you will need the embeddings provider and that should also run 
locally. The embeddings model is used for indexing your codebase and then providing relevant snippets to the model and it needs to run locally through local ollama (not this project, Venice does not provide embeddings API).

Embeddings are very lightweight, so they can run locally on almost any hardware.


