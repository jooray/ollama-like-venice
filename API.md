# API access

Venice.ai has launched their official API access for Pro users. It uses OpenAI-compatible API.

## Getting the tokens

First you need to generate API token. Look at your username in the menu (lower left), click on the three dots, under account info you will see "API Keys - Beta".

After clicking on it, create a name for the token and copy its key - you will not be able to see it again, so save it (although you can always generate different tokens).

## Using with OpenWebUI

This is the syntax of environment variables:

```bash
OPENAI_API_BASE_URLS="https://api.openai.com/v1;https://api.mistral.ai/v1" OPENAI_API_KEYS="<OPENAI_API_KEY_1>;<OPENAI_API_KEY_2>"
```

For example, I run it like this:

```bash
OPENAI_API_BASE_URLS="https://api.venice.ai/api/v1" OPENAI_API_KEYS="<VENICE_API_KEY_HERE>" OLLAMA_BASE_URLS="http://127.0.0.1:11434" ENABLE_RAG_WEB_SEARCH=true RAG_WEB_SEARCH_ENGINE=duckduckgo open-webui serve --port 8082
```

If you still can't see models, you might have to configure it through the user interface. Click on your account, click on Admin Panel / Connections
and set OPENAI base url to https://api.venice.ai/api/v1 and your venice api key. You can have more than one OpenAI-like connection.

Refer to the [original HOWTO](README.md) for how to install and setup OpenWebUI.

## Using with continue.dev

You can configure continue.dev with this snippet:

```json
    {
      "title": "venice llama3.1-405b",
      "provider": "openai",
      "model": "llama-3.1-405b",
      "apiBase": "https://api.venice.ai/api/v1",
      "apiKey": "YOUR_VENICE_API_KEY_HERE"
    },
    {
      "title": "venice qwen-coder",
      "provider": "openai",
      "model": "qwen32b",
      "apiBase": "https://api.venice.ai/api/v1",
      "apiKey": "YOUR_VENICE_API_KEY_HERE"
    },

```

Please note that you should also set up an embedding model (not provided by venice) locally if you want to use @codebase.
Embeddings are a small model and will run on your machine.

Refer to the [original HOWTO](README.md) for how to set continue.dev for development.
