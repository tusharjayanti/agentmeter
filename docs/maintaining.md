# Maintaining

## Screenshots

`docs/images/menubar.png` and `docs/images/menu.png` use demo data, never real usage. To retake them:

1. Write demo sessions in the generic format (see [adapters](adapters.md#your-own-tool)) and a config pointing at them: `{"tools": ["generic"], "roots": {"generic": "<dir>"}}`.
2. Build the app in screenshot mode, which opens its own menu once data has loaded: `swiftc -O -swift-version 5 -D SCREENSHOT macos/AgentmeterBar.swift -o /tmp/bar-shot`.
3. Stop the real app (`launchctl bootout gui/$(id -u)/io.github.agentmeter.bar`), run `AGENTMETER_CONFIG=<demo config> /tmp/bar-shot`, then capture the menu window with `screencapture -o -l <window id>` and the bar with `screencapture -R`.
4. Restart the real app: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/io.github.agentmeter.bar.plist`.

The terminal needs Screen Recording permission, and the screen must be unlocked.

## Homebrew (not published yet)

`Formula/agentmeter.rb` is ready but has a placeholder sha256. To publish:

1. Tag a release (`git tag v0.1.0 && git push --tags`) and take the tarball's sha256: `curl -sL https://github.com/tusharjayanti/agentmeter/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256`.
2. Create a repo named `homebrew-agentmeter` containing `Formula/agentmeter.rb` with that `url` and `sha256`.
3. Then people can `brew tap tusharjayanti/agentmeter && brew install agentmeter`. Add that to the README only once it works.

homebrew-core has notability requirements (stars, age); a personal tap has none.
