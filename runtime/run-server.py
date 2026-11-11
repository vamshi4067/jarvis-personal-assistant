import uvicorn
import openjarvis.server.daemon as daemon
from free_openrouter import attach_free_engine
from freellmapi_engine import attach_router_engine
from chatgpt_engine import attach_chatgpt_engine
from chatgpt_routes import install_chatgpt
import subprocess, sys
from pathlib import Path
router_root = Path.home()/".openjarvis"
# Restore the private Slack listener when this assistant starts.
try:
 from slack_bridge import ensure_worker as ensure_slack_bridge
 if (router_root/'slack-bot.json').exists():ensure_slack_bridge()
except Exception as slack_error:
 print('Slack listener could not start:',type(slack_error).__name__,file=sys.stderr)
# Outbound phone notifications need no inbound public access.
try:
 from phone_alerts import ensure_worker as ensure_phone_alerts
 ensure_phone_alerts()
except Exception as phone_error:
 print('Phone alert sender could not start:',type(phone_error).__name__,file=sys.stderr)
# Keep deterministic daily reminders independent of model availability.
try:
 from recurring_reminders import ensure_worker
 ensure_worker()
except Exception as reminder_error:
 print('Daily reminder worker could not start:', type(reminder_error).__name__, file=sys.stderr)
# The legacy local router is optional and is not auto-started in the public export.
from personal_routes import install_personal
from personal_speech import install_speech_tuning
import piper_speech  # Register update-safe local TTS before discovery.
import apple_speech  # Register the local Apple-GPU recogniser before speech discovery.
from personal_browser import install_browser_tools
from personal_shell import install_shell_tuning
from research_routes import register_research_tool, install_research
from browser_routes import install_browser_routes
from assistant_memory import register_memory_tool
from assistant_work import register_work_tool, install_work
from server import register_teardown_tool, install_teardown
register_teardown_tool()
install_speech_tuning()
install_browser_tools()
install_shell_tuning()
register_research_tool()
register_memory_tool()
register_work_tool()
# This installation has its own launchd supervisor; avoid the shared CLI daemon PID.
def run(app, *, host, port, log_level='info'):
 attach_free_engine(app)
 attach_router_engine(app)
 attach_chatgpt_engine(app)
 install_chatgpt(app)
 install_personal(app)
 from routines import install as install_routines
 install_routines(app)
 from response_speed import install as install_response_speed
 install_response_speed(app)
 install_teardown(app)
 install_research(app)
 install_browser_routes(app)
 install_work(app)
 uvicorn.run(app,host=host,port=port,log_level=log_level)
daemon.run_server=run
from openjarvis.cli import main
main()
