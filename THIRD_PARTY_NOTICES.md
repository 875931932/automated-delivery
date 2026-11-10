# Third-Party Notices

AutoDeliver bundles a Python runtime and third-party packages. Their licenses
remain applicable. Installed package metadata and available license files are
included under `_internal` in the application directory.

Key components and upstream sources:

| Component | Version | Upstream |
| --- | --- | --- |
| Python | 3.11.18 | https://www.python.org/downloads/source/ |
| PySide6 / Qt for Python | 6.12.0 | https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Qt | 6.12.0 | https://download.qt.io/archive/qt/ |
| DrissionPage | 4.1.1.4 | https://github.com/g1879/DrissionPage |
| psutil | 7.2.2 | https://github.com/giampaolo/psutil |
| LangChain | 1.3.12 | https://github.com/langchain-ai/langchain |
| langchain-openai | 1.3.4 | https://github.com/langchain-ai/langchain |
| requests | 2.33.1 | https://github.com/psf/requests |
| Pydantic | 2.13.4 | https://github.com/pydantic/pydantic |
| PyInstaller | 6.22.3 | https://github.com/pyinstaller/pyinstaller |

Qt and PySide6 are used as dynamically linked libraries. Their open-source
licenses include LGPL terms; the applicable license texts are included in the
distribution. Users may replace the relevant shared libraries with compatible
modified versions and may debug modifications as permitted by those licenses.
The application does not impose a restriction on those rights.

The build configuration, including the shared-library layout, is provided in
`packaging/AutoDeliver.spec` in the project repository. Corresponding upstream
sources are available from the links above. Chrome and Edge are discovered on
the target computer and are not included in this distribution.

The Simplified Chinese installer translation is maintained by Zhenghan Yang
and distributed with the Inno Setup source. Its attribution remains in
`packaging/ChineseSimplified.isl`. Inno Setup is a build tool, not an application
runtime dependency.
