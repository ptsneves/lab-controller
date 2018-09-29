#!/usr/bin/env python3

import pexpect
import os
import sys
import time
import argparse
import json
import pexpect

def intersect(l1, l2):
  expected_len = min(len(l1), len(l2))
  intersection_len = len(set(l1) & set(l2))
  return intersection_len == expected_len

def do_power_serial(action, json_power):
  if not intersect(['device', 'baud'], json_power.keys()):
    raise RuntimeError("Make sure that 'device' and 'baud' settings are available for power")

  power_cmd = "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(json_power['device'], json_power['baud'])
  serial_power_conn = pexpect.spawnu(power_cmd, timeout=2, env=os.environ, logfile=sys.stdout)
  if "reset-prompt" in json_power.keys():
     serial_power_conn.send(json_power["reset-prompt"])

  if not intersect(["command", 'eof-character'], json_power.keys()):
    raise RuntimeError("'command' dictionary or 'eof-character' not found in power configuration")

  if not intersect(['on', 'off'], json_power['command'].keys()):
    raise RuntimeError("'on' or 'off' configurations were not found. Please add them")

  if "send" not in json_power['command'][action].keys():
    raise RuntimeError("send string is mandatory for all actions")

  serial_power_conn.send('{}{}'.format(json_power['command'][action]['send'], json_power["eof-character"]))

  if "expect" in json_power['command'][action].keys():
    serial_power_conn.expect(json_power['command'][action]['expect'])

def do_power_usb(action, json_power):
  if not intersect(['usb-address', 'usb-port'], json_power):
   raise RuntimeError("'usb-address' and 'usb-port' are required for usb power control")

  uhubctl_conn = pexpect.spawnu('uhubctl', ['-a', action, '-l', json_power['usb-address'], '-p',
      json_power['usb-port'], '-e'])

  uhubctl_conn.expect_exact('Sent power {} request'.format(action))
  uhubctl_conn.expect_exact('New status for hub {}'.format(json_power['usb-address']))

  if action == "off":
    uhubctl_conn.expect_exact('  Port {}: 0000 {}'.format(json_power['usb-port'], action))
  if action == "on":
    uhubctl_conn.expect('  Port {}: [0-9]{{4}} power'.format(json_power['usb-port']))


def do_power(appliance, action, json_conf):
  if appliance not in json_conf.keys():
    raise RuntimeError("appliance {} not found in configuration.".format(appliance))

  if 'power' not in json_conf[appliance].keys():
    raise RuntimeError("{} does not have power configurations".format(appliance))

  if 'type' not in json_conf[appliance]['power'].keys():
    raise RuntimeError("{} power does not have type defined".format(appliance))

  if json_conf[appliance]['power']['type'] == 'serial':
    do_power_serial(action, json_conf[appliance]['power'])
  elif json_conf[appliance]['power']['type'] == 'usb':
    do_power_usb(action, json_conf[appliance]['power'])
  else:
    raise RuntimeError("type {} is not supported".format(json_conf[appliance]['power']['type']))

def main():
  json_config_path = "./config.json"
  if not os.path.exists(json_config_path):
    raise RuntimeError("Selected configuration file {} not found".format(json_config_path))

  with open(json_config_path) as json_file:
    json_conf = json.load(json_file)

  parser = argparse.ArgumentParser(description='Controls the laboratory relay board and usb hubs.')

  parser.add_argument("-d", "--appliance", choices = json_conf.keys(), required=True)
  parser.add_argument("-p", "--power", choices = ['on', 'off'])
  parser.add_argument('-c', '--config', help='Define the configuration file to use', default='config.json')
  args = parser.parse_args()
  if (args.power):
    do_power(args.appliance, args.power, json_conf)

try:
  main()
except RuntimeError as e:
  print(e)
