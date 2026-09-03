#!/usr/bin/env python3
"""
统一LLM客户端 - 支持多种LLM Provider（含 fallback）
自动检测可用的API Key，优先级：Anthropic(z.ai) > DeepSeek > 智谱(GLM) > OpenAI
主 provider 失败时自动切换 fallback
"""

import os
from typing import Optional, List
import httpx


class LLMClient:
    """统一LLM客户端，支持智谱/DeepSeek/Anthropic/OpenAI，含 fallback"""

    PROVIDERS = {
        "zhipu": {
            "env_keys": ["GLM_API_KEY"],
            "default_model": "glm-4.7",
            "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        },
        "deepseek": {
            "env_keys": ["DEEPSEEK_API_KEY"],
            "default_model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
        },
        "anthropic": {
            "env_keys": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"],
            "default_model": "claude-3-5-sonnet-20241022",
            "base_url_env": "ANTHROPIC_BASE_URL",
        },
        "openai": {
            "env_keys": ["OPENAI_API_KEY"],
            "default_model": "gpt-4o",
        },
    }

    # Provider 自动检测优先级（先匹配到的优先作为主 provider）
    # 首选 z.ai（Anthropic 协议，ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL），DeepSeek 作为备选
    AUTO_DETECT_ORDER = ["anthropic", "deepseek", "zhipu", "openai"]

    # 主 provider 失败时的 fallback 顺序：DeepSeek 优先，其次智谱(GLM)，最后 OpenAI
    FALLBACK_ORDER = ["deepseek", "zhipu", "openai", "anthropic"]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.provider = None
        self.client = None
        self.model = model
        self._fallback_providers: List[str] = []  # 可用的 fallback provider 列表
        self._primary_disabled = False  # 连续失败后临时禁用主 provider
        self._consecutive_failures = 0  # 主 provider 连续失败计数
        self._fast_fail_threshold = 3    # 连续失败 N 次后直接切 fallback

        if provider:
            self._init_provider(provider, api_key, model)
            return

        if api_key:
            self._init_with_key(api_key, model)
            return

        # Auto-detect from environment variables
        self._auto_detect(model)

    def _get_anthropic_key(self) -> Optional[str]:
        """Get Anthropic API key from Claude Code or standard env var."""
        return os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")

    def _init_provider(self, provider: str, api_key: Optional[str], model: Optional[str]):
        """Initialize a specific provider."""
        provider = provider.lower()
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(self.PROVIDERS.keys())}")

        config = self.PROVIDERS[provider]
        key = api_key
        if not key:
            key = None
            for env_key in config["env_keys"]:
                key = os.environ.get(env_key)
                if key:
                    break

        if not key:
            return

        self._try_init_client(provider, key, config, model)

    def _try_init_client(self, provider: str, key: str, config: dict, model: Optional[str]) -> bool:
        """尝试初始化指定 provider 的客户端。成功返回 True，失败返回 False。"""
        try:
            if provider == "anthropic":
                import anthropic
                base_url = os.environ.get(config.get("base_url_env", ""))
                kwargs = {"api_key": key}
                if base_url:
                    kwargs["base_url"] = base_url
                kwargs["timeout"] = httpx.Timeout(180.0, connect=15.0, read=90.0)
                kwargs["max_retries"] = 0
                self.client = anthropic.Anthropic(**kwargs)
                self.provider = "anthropic"
                self.model = model or config["default_model"]
                return True
            elif provider in ("deepseek", "openai"):
                import openai
                base_url = config.get("base_url")
                self.client = openai.OpenAI(api_key=key, base_url=base_url)
                self.provider = provider
                self.model = model or config["default_model"]
                return True
            elif provider == "zhipu":
                import openai
                self.client = openai.OpenAI(
                    api_key=key,
                    base_url=config["base_url"],
                )
                self.provider = "zhipu"
                self.model = model or config["default_model"]
                return True
            return False
        except ImportError:
            return False
        except Exception:
            return False

    def _init_with_key(self, api_key: str, model: Optional[str]):
        """Try to initialize with an explicit API key."""
        # Try anthropic first
        try:
            import anthropic
            base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            kwargs["timeout"] = httpx.Timeout(180.0, connect=15.0, read=90.0)
            kwargs["max_retries"] = 0
            self.client = anthropic.Anthropic(**kwargs)
            self.provider = "anthropic"
            self.model = model or self.PROVIDERS["anthropic"]["default_model"]
            return
        except (ImportError, Exception):
            pass

        for provider_name in ["deepseek", "zhipu", "openai"]:
            try:
                import openai
                base_url = self.PROVIDERS[provider_name].get("base_url")
                self.client = openai.OpenAI(api_key=api_key, base_url=base_url)
                self.provider = provider_name
                self.model = model or self.PROVIDERS[provider_name]["default_model"]
                return
            except Exception:
                continue

    def _auto_detect(self, model: Optional[str]):
        """Auto-detect available provider from environment.
        按 AUTO_DETECT_ORDER 优先级匹配，第一个有 key 的作为主 provider。
        """
        for provider_name in self.AUTO_DETECT_ORDER:
            config = self.PROVIDERS.get(provider_name)
            if not config:
                continue
            key = None
            for env_key in config["env_keys"]:
                key = os.environ.get(env_key)
                if key:
                    break
            if not key:
                continue

            # Auto-detect 时忽略调用方传入的 model，使用 provider 默认模型
            if self._try_init_client(provider_name, key, config, None):
                # 主 provider 初始化成功，收集 fallback 候选
                self._collect_fallbacks(provider_name)
                return

    def _collect_fallbacks(self, primary: str):
        """收集主 provider 之外可用的 fallback provider（按 FALLBACK_ORDER）。"""
        self._fallback_providers = []
        for fb_name in self.FALLBACK_ORDER:
            if fb_name == primary:
                continue
            if self._provider_has_key(fb_name):
                self._fallback_providers.append(fb_name)

    def is_available(self) -> bool:
        """Check if a working LLM provider is configured."""
        return self.client is not None and self.provider is not None

    def get_provider_name(self) -> str:
        """Return the name of the active provider."""
        return self.provider or "none"

    def chat(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        """
        Send a chat message and return the response text.
        主 provider 失败时自动按 FALLBACK_ORDER 切换。
        连续失败达到阈值后，临时禁用主 provider 避免无谓重试。

        Args:
            system_prompt: System prompt
            user_prompt: User message
            max_tokens: Maximum tokens in response

        Returns:
            Response text string
        """
        if not self.is_available():
            raise RuntimeError(
                "No LLM provider available. Set GLM_API_KEY, DEEPSEEK_API_KEY, "
                "ANTHROPIC_AUTH_TOKEN (or ANTHROPIC_API_KEY), or OPENAI_API_KEY."
            )

        import time
        last_error = None

        # 快速失败：主 provider 已被临时禁用，直接走 fallback
        if self._primary_disabled and self._fallback_providers:
            providers_to_try = self._fallback_providers
            primary_skipped = True
        else:
            providers_to_try = [self.provider] + [
                fb for fb in self._fallback_providers if fb != self.provider
            ]
            primary_skipped = False

        for attempt_provider in providers_to_try:
            try:
                if attempt_provider == self.provider and not primary_skipped:
                    result = self._chat_with_current(system_prompt, user_prompt, max_tokens)
                    # 成功：重置失败计数
                    self._consecutive_failures = 0
                    return result
                else:
                    if not primary_skipped:
                        print(f"  \u26a0 主 provider ({self.provider}) 不可用，切换到 fallback: {attempt_provider}")
                    result = self._chat_with_fallback(attempt_provider, system_prompt, user_prompt, max_tokens)
                    return result
            except Exception as e:
                last_error = e
                if attempt_provider == self.provider and not primary_skipped:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self._fast_fail_threshold and not self._primary_disabled:
                        print(f"  \u26a1 主 provider ({self.provider}) 连续失败 {self._consecutive_failures} 次，临时禁用，后续直接走 fallback")
                        self._primary_disabled = True
                provider_label = "主 provider" if (attempt_provider == self.provider and not primary_skipped) else f"fallback {attempt_provider}"
                print(f"  \u26a0 {provider_label} 调用失败: {str(e)[:100]}")
                continue

        raise Exception(f"所有 LLM provider 均失败。最后错误: {last_error}")
    def _chat_with_current(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """使用当前 provider 的 client 发送请求（含 3 次重试）。"""
        import time
        for attempt in range(3):
            try:
                if self.provider == "anthropic":
                    return self._chat_anthropic(system_prompt, user_prompt, max_tokens)
                else:
                    return self._chat_openai_compatible(system_prompt, user_prompt, max_tokens)
            except Exception as e:
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    print(f"  LLM chat error: {str(e)[:80]}, retrying in {wait}s ({attempt+1}/3)...")
                    time.sleep(wait)
                else:
                    raise

    def _chat_with_fallback(self, provider: str, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """使用 fallback provider 发送请求（不重试，失败直接抛给上层切换）。"""
        config = self.PROVIDERS[provider]
        key = self._get_key_for_provider(provider)
        if not key:
            raise Exception(f"Fallback provider {provider} 没有可用的 API key")

        # Anthropic 专有协议：用 anthropic SDK + ANTHROPIC_BASE_URL。
        # 注意 anthropic 的 base_url 存在 "base_url_env" 而非 "base_url"，
        # 且走 messages 接口，不能用 OpenAI 兼容方式调用。
        if provider == "anthropic":
            import anthropic
            base_url = os.environ.get(config.get("base_url_env", ""))
            kwargs = {"api_key": key}
            if base_url:
                kwargs["base_url"] = base_url
            client = anthropic.Anthropic(**kwargs)
            message = client.messages.create(
                model=config["default_model"],
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            for block in message.content:
                if hasattr(block, 'text'):
                    return block.text
            raise RuntimeError("No text block found in response")

        # OpenAI 兼容协议（deepseek / zhipu / openai）
        import openai
        base_url = config.get("base_url")
        client = openai.OpenAI(api_key=key, base_url=base_url)
        model = config["default_model"]

        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def _chat_anthropic(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """Anthropic 专有调用逻辑。"""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        for block in message.content:
            if hasattr(block, 'text'):
                return block.text
        raise RuntimeError("No text block found in response")

    def _chat_openai_compatible(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        """OpenAI 兼容协议调用（zhipu, deepseek, openai）。"""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content

    def _get_key_for_provider(self, provider: str) -> Optional[str]:
        """获取指定 provider 的 API key。"""
        config = self.PROVIDERS.get(provider, {})
        for env_key in config.get("env_keys", []):
            key = os.environ.get(env_key)
            if key:
                return key
        return None

    def _provider_has_key(self, provider: str) -> bool:
        """检查指定 provider 是否有可用的 API key。"""
        return self._get_key_for_provider(provider) is not None
