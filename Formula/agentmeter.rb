# Homebrew formula. Lives in a tap repo named homebrew-agentmeter (see README),
# or install straight from this file: brew install --formula ./Formula/agentmeter.rb
class Agentmeter < Formula
  desc "Token usage and model-routing metrics for agentic coding tools"
  homepage "https://github.com/tusharjayanti/agentmeter"
  url "https://github.com/tusharjayanti/agentmeter/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SHA256_OF_THE_RELEASE_TARBALL"
  license "MIT"
  head "https://github.com/tusharjayanti/agentmeter.git", branch: "main"

  depends_on "python@3.12"

  def install
    python = Formula["python@3.12"].opt_bin/"python3.12"
    system python, "-m", "zipapp", ".", "-m", "agentmeter.cli:main", "-o", "agentmeter", "-p", "#{python}"
    bin.install "agentmeter"
    pkgshare.install "macos", "widget", "examples", "install.sh"
  end

  def caveats
    <<~EOS
      First run walks you through setup:  agentmeter init
      The menu bar app (built locally with swiftc, starts at login) and the report job are optional:
        bash #{pkgshare}/install.sh --widget-only   # or run install.sh from a clone
      Status line for any bar:  agentmeter --status
    EOS
  end

  test do
    assert_match "claude-code", shell_output("#{bin}/agentmeter --tools")
  end
end
