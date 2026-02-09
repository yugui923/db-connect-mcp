# VHS tape file for db-connect-mcp demo
# Run with: vhs demo/demo.tape
#
# Alternative (if VHS doesn't work in containers):
#   asciinema rec -c "uv run python demo/demo.py 2>/dev/null" demo/demo.cast
#   agg --theme monokai --cols 120 --rows 35 demo/demo.cast demo/demo.gif

Output demo/demo.gif
Set Shell bash
Set FontSize 14
Set Width 1000
Set Height 700
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 0ms
Set PlaybackSpeed 1

Hide
Type "uv run python demo/demo.py 2>/dev/null"
Enter
Show
Sleep 75s
