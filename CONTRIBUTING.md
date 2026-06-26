If you meet any problem or request a new feature, you're welcome to [create an issue](https://github.com/anomalyco/opencode/issues/new/choose).

> This is a local fork of [baidu/Unlimited-OCR](https://github.com/baidu/Unlimited-OCR). The original model and `infer.py` belong to the upstream Baidu repo. Issues about the model itself (architecture, training, SGLang patches) should be filed at the upstream repo; issues about the LAN service / web frontend / `ocr-client` wrapper should be filed at this fork.

If you can solve any of [the issues](https://github.com/anomalyco/opencode/issues), you're welcome to send the PR to us.

Before the PR:

* Make sure your code style conforms to [PEP 8](https://peps.python.org/pep-0008/). Indentation is preferred to be 4 spaces.
* The code appears where it should be. For example, code to support an extra inference backend should not be put in general modules like the model definition, while a general modification would better not be hidden inside a very specific backend.
* Has unittests.

After the PR:

* Make sure the CI on [GitHub Actions](https://github.com/anomalyco/opencode/actions) passed.

# Chinese version

如果你遇到问题或需要新功能，欢迎[创建issue](https://github.com/anomalyco/opencode/issues/new/choose)。

> 本仓库是 [baidu/Unlimited-OCR](https://github.com/baidu/Unlimited-OCR) 的本地 fork。原模型与 `infer.py` 版权归上游 Baidu 仓库所有。模型本身（架构、训练、SGLang 补丁）相关 issue 请到上游仓库提交；LAN 服务 / Web 前端 / `ocr-client` 包装相关 issue 请到本 fork 提交。

如果你可以解决某个[issue](https://github.com/anomalyco/opencode/issues)，欢迎发送PR。

发送PR前请确认：

* 你的代码符合[PEP 8代码规范](https://peps.python.org/pep-0008/)。缩进最好为4个空格。
* 代码出现的位置和其定位相符。比如对于某特定推理后端的扩展代码不该出现在模型定义这些较为通用的模块中，而一些非常通用的改动也不该深藏在某个特定后端的代码中。
* 有对应的单测代码。

提交PR后请确认：

* [GitHub Actions](https://github.com/anomalyco/opencode/actions) CI 通过。
