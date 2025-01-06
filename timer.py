#!/usr/bin/python

#
# Timed Internet Manager for EdgeRouter (TIMER)
# 
# (c) 2020 Alexei Kojenov
#  

from __future__ import print_function

import bottle
from bottle import route, template, request, response, redirect

import argparse, json, re, os, subprocess, time, logging
from os import path
from datetime import datetime, timedelta

import cookielib, urllib, urllib2

from urllib2 import Request


#
# environment
#

# the firewall ruleset to use
# it needs to be the internet out ruleset, such as WAN_OUT
ruleset  = 'WAN_OUT'

# rule number range in the ruleset
numStart = 8000
numEnd   = 8999

# DHCP server used by the clients you want to block or allow
dhcpSrv  = 'Kids'

# the EdgeMAX GUI server
# - should always be https://localhost
# - unless you want to use a proxy (for debugging), then set it to ER's external URL
server   = 'https://localhost'

# router admin credentials
# if empty, the existing EdgeRouter session will be used
username = 'timer'
password = 'strongpassword'


#
# global variables
#
cookies = cookielib.CookieJar()
handlers = [
    #urllib2.ProxyHandler({'https': 'http://1.2.3.4:8080'}),
    urllib2.HTTPHandler(),
    urllib2.HTTPSHandler(),
    urllib2.HTTPCookieProcessor(cookies)
  ]
opener = urllib2.build_opener(*handlers)

beakerSessionId = ''


#
# utilities
#
def pretty(prefix, obj):
  return '%s:\n%s' % (prefix, json.dumps(obj,indent=2))


#
# login
#
def login(beakerId):

  global cookies
  global beakerSessionId
  
  if username and password:
    # authenticate with user credentials
    data     = urllib.urlencode({'username':username,'password':password})
    request  = Request(server + '/', data=data)
    response = opener.open(request)

    if not heartbeat():
      return 'invalid username/password'

  elif beakerId:
    # use the existing session cookie
    beakerSessionId = beakerId
    
    if not heartbeat():
      return 'invalid session id'

  else:
    return 'no credentials/session'

  return sanityCheck()


#
# logout
#
def logout():

  if beakerSessionId:
    # do not log out if the existing session was used
    return
  
  request = Request(server + '/logout')
  opener.open(request)


#
# edge api heartbeat
#
def heartbeat():

  request = Request(server + '/api/edge/heartbeat.json')
  request.add_header('X-Requested-With', 'XMLHttpRequest')
  if beakerSessionId:
    request.add_header('Cookie', 'beaker.session.id=' + beakerSessionId)
    
  try:
    response = opener.open(request)
    if response.getcode() == 200:
      data = json.load(response)
      if data['SESSION']:
        return True
  except:
    log.debug('hearbeat caught exception')

  return False


#
# check the configuration
#
def sanityCheck():
  data = batch({'GET':{'firewall':{'name':{ruleset:{}}}}})
  if  not  data['GET']['firewall']['name'][ruleset]:
    return 'invalid ruleset'
  
  data = batch({'GET':{'service':{'dhcp-server':{'shared-network-name':{dhcpSrv:None}}}}})
  if  not  data['GET']['service']['dhcp-server']['shared-network-name'][dhcpSrv]:
    return 'invalid DHCP server'
  
  return ''


#
# edge api batch request
#
def batch(data):
  
  stamp = time.time()

  request = Request(server + '/api/edge/batch.json', data=json.dumps(data))
  request.add_header('X-Requested-With', 'XMLHttpRequest')
  if beakerSessionId:
    request.add_header('Cookie', 'beaker.session.id=' + beakerSessionId)

  response = opener.open(request)
  result   = json.load(response)

  log.debug('%s execution: %d seconds' % (data.keys()[0],round(time.time()-stamp)) )

  return result


#
# get firewall rules
#
def loadRules():
  data     = batch({'GET':{'firewall':{'name':{ruleset:{}}}}})
  allrules =   data['GET']['firewall']['name'][ruleset].get('rule')
  
  if allrules:
    # only return the rules from the specified range
    return {num:rule for num,rule in allrules.items() if numStart <= int(num) < numEnd}

  return {}


#
# initial state (from the firewall ruleset)
#
def loadState():

  enabled = True
  state   = {}
  
  for num, rule in loadRules().items():
    #log.debug(num + ': rule: ' + json.dumps(rule))
    
    # parse the description
    prefix, name, sched = rule['description'].split('|')
    
    if prefix != 'timer':
      log.debug('invalid prefix, this should not happen: %s' % rule['description'])
      continue
    
    if name == 'disabled' and sched == '*':
      enabled = False
      continue

    # get the MAC address
    mac = rule['source']['mac-address']
    
    if mac in state:
      if sched and sched != 'temp':
        # append to the existing schedule
        sched1 = state[mac]['sched'].split()
        if sched not in sched1:
          sched1.append(sched)
          sched1.sort(key=lambda time: int(time.split('-')[0]))
          state[mac]['sched'] = ' '.join(sched1)

    else:
      state[mac] = {
          'new'    : False,
          'name'   : name,
          'sched'  : re.sub('^temp$', '', sched),
          'temp'   : '',
          'forget' : False,
          'ip'     : '',
          'rules'  : []
        }

    state[mac]['rules'].append(num)
    
  log.debug(pretty('loadState() enabled', enabled))
  #log.debug(pretty('loadState() state', state))
  return enabled, state


#
# add current DHCP leases, update IP addresses
#
def addDHCP(state):
  
  # query the leases from the edge api
  request = Request(server + '/api/edge/data.json?data=dhcp_leases')
  if beakerSessionId:
    request.add_header('Cookie', 'beaker.session.id=' + beakerSessionId)

  response = opener.open(request)
  data     = json.load(response)
  
  leases = data['output']['dhcp-server-leases'][dhcpSrv]

  for ip in leases:
    mac  = leases[ip]['mac']
    name = re.sub('^\?$', '', leases[ip]['client-hostname'])

    if not mac in state:
      state[mac] = {
          'new'   : True,
          'name'  : name,
          'sched' : '',
          'temp'  : '',
          'forget': False,
          'ip'    : ip,
          'rules' : []
        }

    state[mac]['ip'] = ip

    if not state[mac]['name']:
      state[mac]['name'] = name


#
# return sorted state (actually, a list)
#   sort by name; if no name, then MAC address
#
def sortState(state):
  return sorted(state.items(), key=lambda item: sortLambda(item[1]['name'], item[0]))

def sortLambda(name, mac):
  if name :
    return name.lower()
  else:
    return '~' + mac


#
# generate firewall rules from the state
# the list of available rule numbers is passed in as a parameter
#
def stateToRules(enabled, state, available):

  rules = {}
  i = 0
  
  for mac, client in sortState(state):

    # do not save the ones that is to be forgotten
    if client['forget']:
      continue
    
    # prioritize the temporary access
    if client['temp']:
      start = datetime.now()
      stop  = start + timedelta(minutes=int(client['temp']))
      
      # EdgeRouter's time specification is very confusing!
      # The rule will match if ANY of the fields matches, and it is impossible
      # to say "this rule stops on this date AND time"
      # Because of that, if the temporary access spills over to the next day,
      # we need to create two rules: one for the date, and one for the date+time
      
      if start.date() != stop.date():
        rules[available[i]] = {
            'description' : 'timer|%s|temp' % client['name'],
            'action'      : 'accept',
            'log'         : 'disable',
            'protocol'    : 'all',
            'source'      : { 'mac-address' : mac },
            'time'        : {
                              'stopdate'  : stop.strftime('%Y-%m-%d')
                            }
          }
        i += 1
      
      # Don't even ask why +1 day all the time!
      # It is super confusing but this is how EdgeRouter firewall rules work
      stopdate = stop + timedelta(days=1)
      rules[available[i]] = {
          'description' : 'timer|%s|temp' % client['name'],
          'action'      : 'accept',
          'log'         : 'disable',
          'protocol'    : 'all',
          'source'      : { 'mac-address' : mac },
          'time'        : {
                            'stopdate'  : stopdate.strftime('%Y-%m-%d'),
                            'stoptime'  : stop.strftime('%H:%M:%S')
                          }
        }
      i += 1
        
      
    if client['sched']:
      # create individual rule for each time slot in the schedule
      for time in client['sched'].split():
        rule = {
            'description' : 'timer|%s|%s' % (client['name'], time),
            'action'      : 'accept',
            'log'         : 'disable',
            'protocol'    : 'all',
            'source'      : { 'mac-address' : mac }
          }
        if time != '*':
          start, stop = time.split('-')
          rule['time'] = {
              'starttime' : datetime.strptime(start, '%H').strftime('%H:%M:%S'),
              'stoptime'  : datetime.strptime(stop,  '%H').strftime('%H:%M:%S')
            }
        rules[available[i]] = rule
        i += 1

    else:
      # no access rule
      rules[available[i]] = {
          'description' : 'timer|%s|' % client['name'],
          'action'      : 'drop',
          'log'         : 'disable',
          'protocol'    : 'all',
          'source'      : { 'mac-address' : mac }
        }
      i += 1
  
  # get the DHCP subnet for the final rule to drop everything else by default
  dhcp = batch({'GET':{'service':{'dhcp-server':{'shared-network-name':{dhcpSrv:None}}}}})
  subnet = dhcp['GET']['service']['dhcp-server']['shared-network-name'][dhcpSrv]['subnet']

  # disable TIMER
  if not enabled:
    rules[numStart] = {
        'description' : 'timer|disabled|*',
        'action'      : 'accept',
        'log'         : 'disable',
        'source'      : { 'address' : subnet.keys()[0] }
      }

  # the final rule
  rules[numEnd] = {
      'description' : 'timer|*|*',
      'action'      : 'drop',
      'log'         : 'disable',
      'source'      : { 'address' : subnet.keys()[0] }
    }

  log.debug(pretty('stateToRules()', rules))
  return rules


#
# save new rules, overwriting the old ones
#
def saveRules(enabled, changed):
  
  #log.debug(pretty('saveRules():', changed))

  # load the existing firewall rules
  rules = loadRules()
  
  toDelete = []
  
  if enabled:
    toDelete += [str(numStart)]
  
  # delete expired temporary access
  toDelete += [ num for num,rule in rules.items()
                    if re.match('^timer\|.*\|temp$', rule['description'])
                       and datetime.strptime('%s %s' % (rule['time'].get('stopdate'),
                                                        rule['time'].get('stoptime','00:00:00')),
                                             '%Y-%m-%d %H:%M:%S') < datetime.now() ]

  # delete rules for all clients that have changed
  for client in changed.values():
    toDelete += [num for num in client['rules']]
  
  log.debug(pretty('toDelete:', toDelete))
  
  # get the list of rule numbers that remain taken
  taken = [ num for num in rules.keys() if num not in toDelete ]
  
  # the list of numbers available for use
  available = [ str(num) for num in range(numStart+1,numEnd) if str(num) not in taken ]

  # convert the internal state to rules
  rules = stateToRules(enabled, changed, available)
  #return  # aleko
  
  if toDelete:
    batch({'DELETE':{'firewall':{'name':{ruleset:{'rule':toDelete}}}}})

  if rules:
    batch({'SET':{'firewall':{'name':{ruleset:{'rule':rules}}}}})
  

#
# ensure the schedule is in correct format
#
def schedValidate(sched):
  
  for time in sched.split():

    if time == '*':
      continue

    elif re.match('^\d{1,2}-\d{1,2}$', time):
      start, stop = time.split('-')
      if int(start) > 23 or int(stop) > 23:
        return False

    else:
      return False
    
  return True


#
# web application
#
@route('/')
def root():
  redirect('/timer')
  

@route('/timer')
def index():

  #log.debug(pretty('headers',['{}: {}'.format(h, request.headers.get(h)) for h in request.headers.keys()]))
  
  message = login(request.get_cookie('beaker.session.id'))
  if message:
    return template('error', title = 'login error', message = message)

  enabled, state = loadState()
  addDHCP(state)
  logout()

  if request.get_cookie('saved'):
    # delete the cookie
    response.set_cookie('saved', 'no', max_age=0, secure=True)
    # render the page with "saved successfully" message
    return template('index',
                    enabled=enabled,
                    oldState=json.dumps(state), state=sortState(state),
                    errors=[])
    
  # render the page with no messages
  return template('index',
                  enabled=enabled,
                  oldState=json.dumps(state), state=sortState(state),
                  errors=None)


@route('/timer', method='POST')
def submit():

  oldEnabled = False if request.forms.get('oldEnabled') == 'False' else True
  enabled    = False if request.forms.get('enabled') is None else True
  log.debug(pretty('oldEnabled', oldEnabled))
  log.debug(pretty('enabled', enabled))
  
  old     = json.loads(request.forms.get('oldState'))
  new     = {}
  changed = {}
  errors  = []
  
  # these arrays contain user input and hidden fields
  macs    = [v.strip() for v in request.forms.getlist('mac')   ]
  names   = [v.strip() for v in request.forms.getlist('name')  ]
  scheds  = [v.strip() for v in request.forms.getlist('sched') ]
  temps   = [v.strip() for v in request.forms.getlist('temp')  ]
  forgets = [v.strip() for v in request.forms.getlist('forget')]

  # iterate and build the new state
  for i in range(len(macs)):
    mac = macs[i]

    new[mac] = {
        'new'    : old[mac]['new'],
        'name'   : names[i],
        'sched'  : scheds[i],
        'temp'   : temps[i],
        'forget' : mac in forgets,
        'ip'     : old[mac]['ip'],
        'rules'  : old[mac]['rules']
      }
    
    # any changes?
    if old[mac] != new[mac]:
      changed[mac] = new[mac]
    
    # validate the name
    if re.match('.*[\'"|].*', new[mac]['name']):
      errors.append('invalid name: ' + new[mac]['name'] + ' (characters \' " | are not allowed)')
  
    # validate the schedule
    if not schedValidate(new[mac]['sched']):
      errors.append('invalid schedude: ' + new[mac]['sched'])

  if enabled != oldEnabled or changed:
    if not errors:
      
      message = login(request.get_cookie('beaker.session.id'))
      if message:
        return template('error', title = 'login error', message = message)

      # everything is good
      saveRules(enabled, changed)
      logout()
      
      # redirect to GET
      response.set_cookie('saved', 'yes', secure=True)
      redirect('/timer')

  else:
    errors.append('no changes')

  return template('index',
                  enabled=True,
                  oldState=json.dumps(old), state=sortState(new),
                  errors=errors)


#
# main
#
parser = argparse.ArgumentParser()
parser.add_argument('-d', '--debug', action='store_true', help='enable debug mode')
parser.add_argument('-l', '--light', action='store_true', help='only to be used by lighttpd')
args = parser.parse_args()

logging.basicConfig()
log = logging.getLogger('timer')
if args.debug:
  logging.getLogger().setLevel(level=logging.DEBUG)
else:
  logging.getLogger().setLevel(level=logging.WARNING)


app = bottle.app()

app.get ('/timer', callback=index,  name='index')
app.post('/timer', callback=submit, name='submit')

bottle.TEMPLATE_PATH.insert(0, os.path.dirname(__file__))

if args.light:
  bottle.run(app=app, server='flup', bindAddress=None, debug=args.debug, reloader=args.debug)
else:
  bottle.run(host='0.0.0.0', port=7143, debug=args.debug, reloader=args.debug)
