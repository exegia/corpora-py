# Terminal demo for the README.
#
#   1. AUTH_REQUIRED=false corpora-api          # in another shell
#   2. mkdir -p /tmp/corpora-demo && cd /tmp/corpora-demo && put a .txt there
#   3. vhs docs/assets/demo.tape
Output docs/assets/demo.gif

Set Shell zsh
Set FontSize 17
Set Width 1180
Set Height 640
Set Padding 22
Set Theme "Catppuccin Mocha"
Set TypingSpeed 28ms

Hide
Type "setopt interactive_comments; cd /tmp/corpora-demo; clear" Enter
Show

Type "# 1. turn a text file into a corpus" Enter
Sleep 500ms
Type "curl -sF file=@gettysburg.txt -F source_format=plain -F name=Gettysburg \" Enter
Type "  localhost:8000/convert | tee job.json | jq -r .job_id" Enter
Sleep 2s
Type "JOB=$(jq -r .job_id job.json)" Enter
Sleep 400ms

Type "# 2. check the job" Enter
Sleep 400ms
Type "curl -s localhost:8000/convert/$JOB | jq '{status, last_log}'" Enter
Sleep 2s

Type "# 3. read it back" Enter
Sleep 400ms
Type "curl -s localhost:8000/convert/$JOB/sections | jq -c '.items[0]'" Enter
Sleep 2s
Type 'curl -s "localhost:8000/convert/$JOB/content?limit=1" | jq -r ".passages[0].text"' Enter
Sleep 2500ms

Type "# 4. take the archive" Enter
Sleep 400ms
Type "curl -sOJ localhost:8000/convert/$JOB/download && ls -lh *.corpus" Enter
Sleep 3s
