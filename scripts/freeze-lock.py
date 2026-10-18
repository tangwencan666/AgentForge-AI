"""Freeze this project environment, preserving platform requirements for Linux images."""

from maintenance_policy import cli_gate, maintenance_action
cli_gate(__file__, __name__)

@maintenance_action('dependency.freeze')
def main():
    from pathlib import Path
    import subprocess
    import sys

    root=Path(__file__).resolve().parents[1]
    lines=subprocess.check_output([sys.executable,"-m","pip","freeze"],text=True).splitlines()
    result=[]
    for line in lines:
        if line.startswith(("#","-e")) or "agentforge-backend" in line: continue
        if line.lower().startswith("pywin32=="): line+='; sys_platform == "win32"'
        result.append(line)
    (root/"backend/requirements.lock").write_text("\n".join(result)+"\n",encoding="utf-8")
    print("Project dependency lock written with platform markers")


if __name__ == "__main__":
    main()
