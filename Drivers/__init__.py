import io
import logging
import os
import re
import sys
import zipfile
from distutils.version import LooseVersion
from urllib.request import urlopen, urlretrieve

from selenium.webdriver import Chrome as _Chrome
from selenium.webdriver import ChromeOptions as _ChromeOptions

logger = logging.getLogger(__name__)


TARGET_VERSION = 0


class Chrome:
    def __new__(cls, *args, enable_console_log=False, **kwargs):

        if not ChromeDriverManager.installed:
            ChromeDriverManager(*args, **kwargs).install()
        if not ChromeDriverManager.selenium_patched:
            ChromeDriverManager(*args, **kwargs).patch_selenium_webdriver()
        if not kwargs.get("executable_path"):
            kwargs["executable_path"] = "./{}".format(
                ChromeDriverManager(*args, **kwargs).executable_path
            )
        if not kwargs.get("options"):
            kwargs["options"] = ChromeOptions()
        instance = object.__new__(_Chrome)
        instance.__init__(*args, **kwargs)

        instance._orig_get = instance.get

        def _get_wrapped(*args, **kwargs):
            if instance.execute_script("return navigator.webdriver"):
                instance.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": """
                            Object.defineProperty(window, 'navigator', {
                                value: new Proxy(navigator, {
                                has: (target, key) => (key === 'webdriver' ? false : key in target),
                                get: (target, key) =>
                                    key === 'webdriver'
                                    ? undefined
                                    : typeof target[key] === 'function'
                                    ? target[key].bind(target)
                                    : target[key]
                                })
                            });
                        """
                        + (
                            "console.log = console.dir = console.error = function(){};"
                            if not enable_console_log
                            else ""
                        )
                    },
                )
            return instance._orig_get(*args, **kwargs)

        instance.get = _get_wrapped

        original_user_agent_string = instance.execute_script(
            "return navigator.userAgent"
        )
        instance.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {"userAgent": original_user_agent_string.replace("Headless", ""),},
        )
        logger.info(f"starting undetected_chromedriver.Chrome({args}, {kwargs})")
        return instance


class ChromeOptions:
    def __new__(cls, *args, **kwargs):
        if not ChromeDriverManager.installed:
            ChromeDriverManager(*args, **kwargs).install()
        if not ChromeDriverManager.selenium_patched:
            ChromeDriverManager(*args, **kwargs).patch_selenium_webdriver()

        instance = object.__new__(_ChromeOptions)
        instance.__init__()
        instance.add_argument("start-maximized")
        instance.add_experimental_option("excludeSwitches", ["enable-automation"])
        instance.add_argument("--disable-blink-features=AutomationControlled")
        return instance


class ChromeDriverManager(object):

    installed = False
    selenium_patched = False
    target_version = None

    DL_BASE = "https://chromedriver.storage.googleapis.com/"

    def __init__(self, executable_path=None, target_version=None, *args, **kwargs):

        _platform = sys.platform

        if TARGET_VERSION:
            # use global if set
            self.target_version = TARGET_VERSION

        if target_version:
            # use explicitly passed target
            self.target_version = target_version  # user override

        if not self.target_version:
            # none of the above (default) and just get current version
            self.target_version = self.get_release_version_number().version[
                0
            ]  # only major version int

        self._base = base_ = "chromedriver{}"

        exe_name = self._base
        if _platform in ("win32",):
            exe_name = base_.format(".exe")
        if _platform in ("linux",):
            _platform += "64"
            exe_name = exe_name.format("")
        if _platform in ("darwin",):
            _platform = "mac64"
            exe_name = exe_name.format("")
        self.platform = _platform
        self.executable_path = executable_path or exe_name
        self._exe_name = exe_name

    def patch_selenium_webdriver(self_):
        import selenium.webdriver.chrome.service
        import selenium.webdriver

        selenium.webdriver.Chrome = Chrome
        selenium.webdriver.ChromeOptions = ChromeOptions
        self_.__class__.selenium_patched = True

    def install(self, patch_selenium=True):
        if not os.path.exists(self.executable_path):
            self.fetch_chromedriver()
            if not self.__class__.installed:
                if self.patch_binary():
                    self.__class__.installed = True

        if patch_selenium:
            self.patch_selenium_webdriver()

    def get_release_version_number(self):
        path = (
            "LATEST_RELEASE"
            if not self.target_version
            else f"LATEST_RELEASE_{self.target_version}"
        )
        return LooseVersion(urlopen(self.__class__.DL_BASE + path).read().decode())

    def fetch_chromedriver(self):
        base_ = self._base
        zip_name = base_.format(".zip")
        ver = self.get_release_version_number().vstring
        if os.path.exists(self.executable_path):
            return self.executable_path
        urlretrieve(
            f"{self.__class__.DL_BASE}{ver}/{base_.format(f'_{self.platform}')}.zip",
            filename=zip_name,
        )
        with zipfile.ZipFile(zip_name) as zf:
            zf.extract(self._exe_name)
        os.remove(zip_name)
        if sys.platform != "win32":
            os.chmod(self._exe_name, 0o755)
        return self._exe_name

    def patch_binary(self):
        linect = 0
        with io.open(self.executable_path, "r+b") as fh:
            for line in iter(lambda: fh.readline(), b""):
                if b"cdc_" in line:
                    fh.seek(-len(line), 1)
                    newline = re.sub(b"cdc_.{22}", b"xxx_undetectedchromeDRiver", line)
                    fh.write(newline)
                    linect += 1
            return linect


def install(executable_path=None, target_version=None, *args, **kwargs):
    ChromeDriverManager(executable_path, target_version, *args, **kwargs).install()