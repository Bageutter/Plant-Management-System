@echo off
rem Open one Windows Terminal window with the six panes the showcase video shows:
rem   Ollama | MCP server | RAG server             (top row, live logs)
rem   Multi-Agent server | docker compose | shell  (bottom row; the shell is for the demo commands)
rem The servers themselves are already running detached (scripts/demo/wsl-demo-up.sh);
rem these panes tail their logs, which is the same text the processes print.
rem Note: Windows Terminal splits its command line on every ";", even inside quotes,
rem so the pane commands below join steps with "&&" and never use ";".
set REPO=/mnt/c/Users/Guhan.Sundar/Documents/Advanced Software Dev/Assignment/Plant-Management-System/.claude/worktrees/video-script-assignment-d4e8fa
set W=wsl -d Ubuntu -- bash -c

wt -w new new-tab --title "Ollama (AI-Mode) :11434" %W% "echo '$ ollama serve   (AI-Mode, host process, GPU)' && tail -n 8 -f ~/pms-logs/ollama.log" ; split-pane -V --title "MCP server :5105" %W% "echo '$ python ai-services/mcp-server/server.py' && tail -n 8 -f ~/pms-logs/mcp-server.log" ; split-pane -V --title "RAG server :5106" %W% "echo '$ python ai-services/rag-server/app.py' && tail -n 8 -f ~/pms-logs/rag-server.log" ; move-focus left ; move-focus left ; split-pane -H --title "Multi-Agent Server :8003" %W% "echo '$ python ai-services/multi-agent-server/app.py' && tail -n 8 -f ~/pms-logs/multi-agent-server.log" ; move-focus right ; split-pane -H --title "docker compose :3000" %W% "echo '$ docker compose up -d' && cd '%REPO%' && COMPOSE_PROJECT_NAME=plant-management-system docker compose -f docker-compose.yml -f docker-compose.demo.yml logs -f --tail 3" ; move-focus right ; split-pane -H --title "demo commands" %W% "cd '%REPO%' && export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin COMPOSE_PROJECT_NAME=plant-management-system && clear && echo 'Ready. Scripts: bash scripts/test/local-deployment-check.sh | bash scripts/test/multi-agent-vgarden.sh | bash scripts/test/multi-agent-health.sh' && exec bash"
