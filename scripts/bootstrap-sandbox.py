"""Append project-only development role credentials; never display their values."""
from pathlib import Path
import argparse
import re
import secrets
from dotenv import dotenv_values

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--image-id",required=True)
parser.add_argument("--replace-approved-image",action="store_true",help="Explicit local maintainer rotation invalidates old pending approvals")
args=parser.parse_args()
if not re.fullmatch(r"sha256:[a-f0-9]{64}",args.image_id):
    raise SystemExit("A reviewed immutable image ID is required")
target=root/".env"
values=dotenv_values(target)
changes={}
for key in ("AGENTFORGE_SANDBOX_RUNNER_TOKEN","AGENTFORGE_SANDBOX_APPROVER_TOKEN"):
    if not values.get(key): changes[key]=secrets.token_hex(32)
image_key="AGENTFORGE_SANDBOX_IMAGE_ID"
if values.get(image_key) and values[image_key]!=args.image_id and not args.replace_approved_image:
    raise SystemExit("Existing approved image differs; review and rotate its project registration explicitly")
if not values.get(image_key): changes[image_key]=args.image_id
if args.replace_approved_image and values.get(image_key)!=args.image_id:
    from dotenv import set_key
    set_key(target,image_key,args.image_id)
if changes:
    with target.open("a",encoding="utf-8") as file:
        file.write("\n# P3 project-only protected control-plane references\n")
        for key,value in changes.items(): file.write(f"{key}={value}\n")
print("Project sandbox configuration registered; protected credential values were not displayed")
