import subprocess, sys
r = subprocess.run([sys.executable,"-m","pytest","tests/test_analyzer_integration.py",
  "-p","no:randomly","-k","api_analysis_does_not_die or subprocess_safe","--tb=short","-q"],
  capture_output=True, text=True)
out = r.stdout + r.stderr
for line in out.splitlines()[-40:]:
    print(line)
