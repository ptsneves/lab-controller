#!/usr/bin/env python3

import os
import sys
import argparse
import json
import pexpect

def intersect(l1, l2):
  expected_len = min(len(l1), len(l2))
  intersection_len = len(set(l1) & set(l2))
  return intersection_len == expected_len

def check_serial_settings(json_appliance_section):
  if not intersect(['device', 'baud', 'eof-character'], json_appliance_section.keys()):
    raise RuntimeError("Make sure that 'device' 'baud' and 'eof-character' settings are"
      " available in appliance section")

def check_applicance(appliance, json_conf):
  if appliance not in json_conf.keys():
    raise RuntimeError("appliance {} not found in configuration.".format(appliance))

def check_appliance_section(appliance_section, json_appliance):
  if appliance_section  not in json_appliance.keys():
    raise RuntimeError("Cannot find {} configurations".format(appliance_section))

def check_device_type(json_appliance_section):
  if 'type' not in json_appliance_section.keys():
    raise RuntimeError("type not defined in appliance section")

def do_power_group(group_json, action, global_json_conf):
  print(group_json)
  if "devices" not in group_json.keys():
    raise RuntimeError("Found a group with no devices. Please correct the type or add devices")

  for device in group_json["devices"]:
    do_power(device, action, global_json_conf)

def check_expect_instance(json_expect_instance):
  if not intersect(["text", "timeout"], json_expect_instance.keys()):
    raise RuntimeError("'text' and 'timeout' data is mandatory for each expect call")
  if not json_expect_instance["timeout"].isdigit():
    raise RuntimeError("'timeout' is not a number")

def check_json_expect(json_expect):
  if not "expect" in json_expect.keys():
    raise RuntimeError("At least one expect root key is required in json")

  json_expect_array = json_expect["expect"]
  for json_expect_instance in json_expect_array:
    print(json.dumps(json_expect_instance))
    check_expect_instance(json_expect_instance)

def check_usb_json(json_usb):
  if not intersect(['usb-address', 'usb-port'], json_usb):
    raise RuntimeError("'usb-address' and 'usb-port' are required for usb power control")

def check_command(json_communication):
  if not intersect(["command"], json_communication.keys()):
    raise RuntimeError("'command' dictionary or 'eof-character' not found in power configuration")

  if not intersect(['on', 'off'], json_communication['command'].keys()):
    raise RuntimeError("'on' or 'off' configurations were not found. Please add them")

  for action in json_communication['command'].keys():
    for json_action_command in json_communication['command'][action]:
      if "send" not in json_action_command.keys():
        raise RuntimeError("send string is mandatory for all actions")

def do_host_command(execute, expects = [], shell = False, exact = True):
  if shell:
    execute = "bash -c '{}'".format(execute)

  command_conn = pexpect.spawnu(execute, env = os.environ, codec_errors = 'ignore')
  if expects != []:
    for expect in expects:
      if exact:
        command_conn.expect_exact(expect)
      else:
        command_conn.expect(expect)

  if command_conn.wait() != 0:
    raise RuntimeError("Host Command did not execute successfully: {}".format(execute))

def do_power_serial(action, json_power):
  check_serial_settings(json_power)
  check_command(json_power)

  power_cmd = "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 " \
      "file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(json_power['device'],
       json_power['baud'])

  serial_power_conn = pexpect.spawnu(power_cmd, timeout=2, env=os.environ, codec_errors='ignore')
  if "reset-prompt" in json_power.keys():
    serial_power_conn.send(json_power["reset-prompt"])
    if "reset-expect" in json_power.keys():
      serial_power_conn.expect(json_power["reset-expect"])

  for json_action_command in json_power['command'][action]:
    serial_power_conn.send('{}{}'.format(json_action_command['send'], json_power["eof-character"]))

    if "expect" in json_action_command.keys():
      serial_power_conn.expect(json_action_command['expect'])

def do_power_usb(action, json_power):
  check_usb_json(json_power)

  execute = 'uhubctl -a {} -l {} -p {}'.format(action, json_power['usb-address'], json_power['usb-port'])

  expects = []
  expects.append('Sent power {} request'.format(action))
  expects.append('New status for hub {}'.format(json_power['usb-address']))

  if action == "off":
    expects.append('  Port {}: 0000 {}'.format(json_power['usb-port'], action))
  if action == "on":
    expects.append('  Port {}: [0-9]{{4}} power'.format(json_power['usb-port']))

  do_host_command(execute, expects, exact = False)

def do_power_command(action, json_power):
  check_command(json_power)

  if "shell" not in json_power.keys():
    raise RuntimeError("Host commands need to specify if commands are shell")

  shell = json_power["shell"]

  for json_action_command in json_power["command"][action]:
    expect = []
    if "expect" in json_action_command.keys():
      expect = json_action_command["expect"]

    do_host_command(json_action_command["send"], expect, shell)

def do_power(appliance, action, json_conf):
  appliance_section = 'power'

  check_applicance(appliance, json_conf)
  json_appliance = json_conf[appliance]
  check_appliance_section(appliance_section, json_appliance)
  json_appliance_section = json_appliance[appliance_section]

  ran_power = False

  for communication_method in json_appliance_section:
    json_communication_method = json_appliance_section[communication_method]
    check_device_type(json_communication_method)
    if json_communication_method['type'] == 'serial':
      try:
        do_power_serial(action, json_communication_method)
        ran_power = True
      except RuntimeError as e:
        print(e)
    elif json_communication_method['type'] == 'usb':
      try:
        do_power_usb(action, json_communication_method)
        ran_power = True
      except RuntimeError as e:
        print(e)
    elif json_communication_method['type'] == 'host':
        do_power_command(action, json_communication_method)
        ran_power = True
    elif json_communication_method['type'] == 'group':
        do_power_group(json_communication_method, action, json_conf)
        ran_power = True
    else:
      raise RuntimeError("type {} is not supported".format(json_communication_method['type']))

  if not ran_power:
    raise RuntimeError("Did not successfully turn power on for appliance {}".format(appliance))

def get_serial_device(appliance, appliance_section, json_conf):
  found_serial = False
  device_data_result = None
  check_applicance(appliance, json_conf)
  json_appliance = json_conf[appliance]

  check_appliance_section(appliance_section, json_appliance)
  json_appliance_section = json_appliance[appliance_section]
  for com_type in json_appliance_section:
    json_communication = json_appliance_section[com_type]
    check_device_type(json_communication)

    if json_communication['type'] == 'serial':
      if found_serial:
        raise RuntimeError("Found duplicated serial device for same appliance section. Correct this.")
      check_serial_settings(json_communication)
      device_data_result = json_communication
      found_serial = True

  if not found_serial:
    raise RuntimeError("Cannot get serial device for a non serial appliance section")

  return device_data_result

def expect_on_serial(appliance, json_expect, json_conf):
  json_serial = get_serial_device(appliance, "communications", json_conf)
  check_json_expect(json_expect)

  serial_cmd = "socat -t0 STDIO,raw,echo=0,escape=0x03,nonblock=1 file:{},b{},cs8,parenb=0,cstopb=0,clocal=0,raw,echo=0".format(json_serial['device'], json_serial['baud'])
  print(serial_cmd)
  serial_conn = pexpect.spawnu(serial_cmd, timeout=2, env=os.environ, codec_errors='ignore', logfile=sys.stdout)

  if "reset-prompt" in json_serial.keys():
    serial_conn.send(json_serial["reset-prompt"])
    if "reset-expect" in json_serial.keys():
      serial_conn.expect(json_serial["reset-expect"])

  json_expect_array = json_expect["expect"]
  for expect_entry in json_expect_array:
    serial_conn.expect(expect_entry['text'], float(expect_entry['timeout']))

def main():
  json_config_path = "./config.json"
  if not os.path.exists(json_config_path):
    raise RuntimeError("Selected configuration file {} not found".format(json_config_path))

  with open(json_config_path) as json_file:
    json_conf = json.load(json_file)

  parser = argparse.ArgumentParser(description='Controls the laboratory relay board and usb hubs.')
  arg_mutex = parser.add_mutually_exclusive_group(required=True)

  arg_mutex.add_argument("-p", "--power", choices = ['on', 'off'])
  parser.add_argument("-d", "--appliance", choices = json_conf.keys(), required=True)
  arg_mutex.add_argument('--get-serial-device')
  arg_mutex.add_argument('--json-expect-on-serial')

  args = parser.parse_args()
  if args.power:
    do_power(args.appliance, args.power, json_conf)
  elif args.get_serial_device:
    result_json = get_serial_device(args.appliance, args.get_serial_device, json_conf)
    print(json.dumps(result_json, sort_keys=True, indent=2))
  elif args.json_expect_on_serial:
    json_expect_on_serial = json.loads(args.json_expect_on_serial)
    expect_on_serial(args.appliance, json_expect_on_serial, json_conf)
  else:
    raise ValueError("Impossible: Mandatory options not passed in arguments")

try:
  main()
except RuntimeError as e:
  print(e)
  exit(1)
