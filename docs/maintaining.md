# Maintaining

## Screenshots

The README images in `docs/images/` use demo data, never real usage, and made-up projects and prompts.

- `hero.png`: the menu bar item drawn in HTML (same font and sizes as the app) with the real menu window composited under it, on a gradient.
- `terminal.png`: the real CLI output (`FORCE_COLOR=1 agentmeter`) converted from ANSI to HTML in a window frame.
- `menu.png`: the menu window alone (step 3 below), with numbered markers drawn over it in HTML; the README section "The menu, part by part" explains each numbered part.
- `tui.png`: `agentmeter tui` drawn from `tui.frame(state, 100, 20)` (plain lines with styles) as HTML in a window frame; no terminal capture needed.
- `report.png`: a real saved report rendered from its Markdown in a window frame.

To retake them:

1. Write demo sessions in the generic format (see [adapters](adapters.md#your-own-tool)) covering at least three weeks, and a config pointing at them: `{"tools": ["generic"], "roots": {"generic": "<dir>"}, "period": {"start": "<a Friday three weeks back>", "length": "1w"}}`. Save demo reports with `AGENTMETER_CONFIG=<demo config> agentmeter --save <demo reports dir>`.
2. Build the app in screenshot mode, which opens its own menu once data has loaded: `swiftc -O -swift-version 5 -D SCREENSHOT macos/AgentmeterBar.swift -o /tmp/bar-shot`.
3. Stop the real app (`launchctl bootout gui/$(id -u)/io.github.agentmeter.bar`), run `AGENTMETER_CONFIG=<demo config> AGENTMETER_REPORTS=<demo reports dir> /tmp/bar-shot`, and capture the menu window alone with `screencapture -o -l <window id>` (find the id with `CGWindowListCopyWindowInfo`, owner `bar-shot`).
4. Restart the real app: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.agentmeter.bar.plist`.
5. Render the HTML pages with headless Chrome at 2x: `--headless=new --force-device-scale-factor=2 --default-background-color=00000000 --screenshot`.

The terminal needs Screen Recording permission, and the screen must be unlocked.

## Homebrew (not published yet)

`Formula/agentmeter.rb` is ready but has a placeholder sha256. To publish:

1. Tag a release (`git tag v0.1.0 && git push --tags`) and take the tarball's sha256: `curl -sL https://github.com/tusharjayanti/agentmeter/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256`.
2. Create a repo named `homebrew-agentmeter` containing `Formula/agentmeter.rb` with that `url` and `sha256`.
3. Then people can `brew tap tusharjayanti/agentmeter && brew install agentmeter`. Add that to the README only once it works.

homebrew-core has notability requirements (stars, age); a personal tap has none.
