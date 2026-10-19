"""Finite child for real OS competition/crash tests with a fake Runner port."""
import sys
from retirement_boundary import Boundary, TARGET, OPERATOR, APPROVER
from app.sandbox.retirement_control import OfflineRetirementController, ControlRefused

directory,grant,mode=sys.argv[1:]
boundary=Boundary(directory);boundary.sealed=True;boundary.restart='no';boundary.closed=True
boundary.actor=OPERATOR;boundary.crash=mode=='crash'
try:
    controller=OfflineRetirementController(directory,TARGET,boundary,OPERATOR,APPROVER)
    controller.execute(grant)
except ControlRefused:
    raise SystemExit(2) from None
