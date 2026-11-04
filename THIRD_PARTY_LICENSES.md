# Third-Party Licenses and Notices

AoE2 Trigger Studio+ uses third-party open-source software. The licenses below apply to those third-party components only. AoE2 Trigger Studio+ itself is intended to be distributed under the GNU General Public License version 3.0 (GPL-3.0); see the repository `LICENSE` file.

This is a source-repository notice. Before publishing a packaged Windows binary, audit the exact components bundled in that release and include all applicable full license texts and copyright notices.

## AoE2ScenarioParser

**Version currently used:** 0.9.8  
**License:** GNU General Public License version 3 (GPL-3.0)

AoE2 Trigger Studio+ uses AoE2ScenarioParser to read and modify Age of Empires II scenario data.

AoE2ScenarioParser remains the copyright of its respective authors and contributors and is distributed under its own license terms. Packaged distributions should retain the applicable copyright and GPL-3.0 information and comply with GPL source-availability requirements.

## PySide6 / Qt for Python

**Version currently used:** 6.11.2  
**Licensing:** Open-source PySide6 / Qt licensing includes LGPLv3/GPL terms; Qt also offers commercial licensing.

AoE2 Trigger Studio+ uses PySide6 for its desktop user interface. Qt for Python also contains third-party components under their own licenses. Applicable Qt/PySide6 license texts and third-party notices should be retained with packaged distributions where required.

Related packages in the development environment include:

- PySide6_Addons
- PySide6_Essentials
- shiboken6

## PyInstaller

**Version observed in the development environment:** 6.22.3  
**Use:** Packaging Windows test builds

PyInstaller is distributed under the GPL with an exception that permits applications packaged by PyInstaller to be distributed under the application's chosen license, subject to the licenses of the bundled dependencies.

PyInstaller itself is build tooling and does not replace AoE2 Trigger Studio+'s own license.

### PyInstaller Community Hooks

PyInstaller community hooks may be used during packaging. Standard hooks and runtime hooks remain subject to their applicable upstream license terms. Any hook code actually included in a release should be covered by the final release license audit.

## Python

**Development version:** 3.10.6  
**License:** Python Software Foundation License

PyInstaller Windows builds may bundle the Python runtime. Python remains subject to the Python Software Foundation's license terms. Include the applicable Python license text with packaged distributions where required.

## Other Python Dependencies

The installed environment also includes direct or transitive dependencies such as:

- deprecation
- ordered-set
- typing-extensions

Additional transitive dependencies may be included in packaged builds.

The exact license for every bundled version of these packages has not yet been recorded in this source-repository notice. Before publishing the first downloadable binary release, generate an inventory from the final release environment and verify the license and notice requirements for every bundled package.

## Binary Distribution Checklist

Before publishing a downloadable AoE2 Trigger Studio+ Windows package:

1. Freeze the exact release environment and record package versions.
2. Inspect the PyInstaller build to identify all bundled Python and Qt components.
3. Verify the license of every bundled dependency.
4. Include all applicable third-party license texts and copyright notices.
5. Include the AoE2 Trigger Studio+ `LICENSE` file.
6. Include this notice, updated to match the actual release contents.
7. Make corresponding source available where required by GPL-covered components.

A future release archive may use a layout similar to:

```text
AoE2 Trigger Studio+/
├── AoE2 Trigger Studio+.exe
├── LICENSE
├── THIRD_PARTY_LICENSES.md
├── licenses/
│   ├── AoE2ScenarioParser-GPL-3.0.txt
│   ├── PySide6-Qt-license.txt
│   ├── Qt-third-party-notices.txt
│   ├── Python-PSF-license.txt
│   └── additional-dependency-licenses...
└── _internal/
```

## Age of Empires Notice

AoE2 Trigger Studio+ is an independent community project. Third-party software licenses do not imply endorsement by Microsoft, Xbox Game Studios, World's Edge, Forgotten Empires, or the authors of any dependency.

Age of Empires and Age of Empires II are trademarks of their respective owners.

## Maintaining This File

Review this file whenever:

- AoE2ScenarioParser is upgraded;
- PySide6 / Qt is upgraded;
- Python is upgraded;
- the packaging process changes;
- dependencies are added or removed; or
- a new binary release is prepared.

The final binary-release license bundle should be generated from the exact dependency versions contained in that release rather than relying solely on this development-time notice.
