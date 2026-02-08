# VHS tape file for db-connect-mcp demo
# Run with: vhs demo/demo.tape
#
# Alternative (if VHS doesn't work in containers):
#   asciinema rec -c "uv run python demo/demo.py 2>/dev/null" demo/demo.cast
#   agg --theme monokai demo/demo.cast demo/demo.gif

Output demo/demo.gif
Set Shell bash
Set FontSize 14
Set Width 1200
Set Height 800
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 0ms
Set PlaybackSpeed 0.5

Sleep 500ms
Type "uv run python demo/demo.py 2>/dev/null"
Enter
Sleep 20s
Sleep 2s
