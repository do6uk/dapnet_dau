#!/usr/bin/env python3

# copyright (c) 2022 by Rainer Fiedler DO6UK
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

import time,os,sys,socket,re,datetime,signal
from queue import Queue
from threading import Thread

# host/ip of fake-core
tcp_address = "127.0.0.1"
tcp_port = 43434

# timeslots for local transmitter
client_slots = '2389D'

#callsing of local transmitter
client_callsign = 'do6uk-dau'

# credentials - actually ignored by fake
client_key = '01234'		#actually ignored

# use unix-socket to submit messages to fake-core
use_message_socket = True
server_message_socket = '/tmp/dapnet_dau.s'

# user named-pipe to submit messages to fake-core
server_message_pipe = './dapnet_dau.fifo'
use_message_pipe = True

# seconds to check client-conn is still working - will resend 3:+0000
core_ping = 30

# seconds that messages will kept in msg_history - should be 1 cycle of all slots
msg_blocktime = 103

# enable debugging (more useless information at console ;-)
debug = False

# enable silentmode (mostly no output) can be reached by --silent in cli
silent = False


### do not edit below this line

version = '20221205'

LOGIN_PATTERN = re.compile(r'^\[(.+)\s(v.+)\s(\w{2}\d\w{2,3})\s(.+)]')
TIME_PATTERN = re.compile(r'^2\:(.{4}):(.{4})')
MSG_PATTERN = re.compile(r'^(\d):(\d):(\d+):(\d):(.+)')
MSG_ACK_PATTERN = re.compile(r'^#(..)\s([\+])')

send_time_utc = True
send_time_local = True

running = True
client_online = False

bind_max_try = 10

msg_history = {}

sock_reader = None
pipe_reader = None
server = None
client_conn = None

print('[dau_core]','starting dapnet_dau v%s ...'%version)

if '--silent' in sys.argv:
	if debug: print('[dau_core]','running silent mode will set  debug = False')
	silent = True
	debug = False

def time_skyper ():
	now = datetime.datetime.utcnow()
	time_string = now.strftime("%H%M%S %d%m%y")
	# '5:1:9C8:0:%s'%time_string
	return time_string

def time_swissphone (localtime = False):
	if localtime:
		now = datetime.datetime.now()
	else:
		now = datetime.datetime.utcnow()
	time_string = now.strftime("%H%M%d%m%y")
	# '6:1:287E0:3:XTIME=%sXTIME=%s'%(time_string,time_string)
	return 'XTIME=%sXTIME=%s'%(time_string,time_string)

def time_alphapoc(localtime = False):
	if localtime:
		now = datetime.datetime.now()
	else:
		now = datetime.datetime.utcnow()
	time_string = now.strftime("%Y%m%d%H%M%S")
	# '6:1:287EA:3:YYYYMMDDHHMMSS%s'%time_string
	return 'YYYYMMDDHHMMSS%s'%time_string

def make_message(m_type, m_speed, m_ric, m_function, message):
	global last_msg, client_online, debug
	
	if client_online:
		if last_msg >= 0xFF:
			last_msg = 0
		else:
			last_msg += 1
	else:
		last_msg = 0
	
	return '#{:02X} {:1}:{}:{:x}:{:1}:{}'.format(last_msg,m_type,m_speed,m_ric,m_function,message)

def send_data(data, wait_response = True, silent = False):
	global client_conn, client_online, debug
	
	if client_online:
		if not silent: print('[CLIENT]','MSG_SEND', data)
		data += '\r\n'
		try:
			client_conn.sendall(data.encode("utf-8"))
		except BrokenPipeError:
			client_online = False
			return False
	
		if wait_response:
			time.sleep(0.1)
			client_conn.settimeout(2)
			rec_data = client_conn.recv(1024).decode('utf-8')
			client_conn.settimeout(None)
			if rec_data:
				msg_ack = MSG_ACK_PATTERN.match(rec_data)
				if msg_ack:
					if not silent: print('[CLIENT]','MSG_ACK',msg_ack[1])
					return msg_ack[1]
				elif rec_data.rstrip() == '+':
					if not silent: print('[CLIENT]','DATA_ACK')
					return True
				else:
					if not silent: print('[CLIENT]','received invalid response',rec_data)
					return rec_data
			else:
				if not silent: print('[CLIENT]','not answered - message dropped')
				client_online = False
				return False
		else:
			return True
	else:
		if not silent: print('[CLIENT]','not connected - message dropped')
		client_online = False
		return False

def send_queue():
	global running, client_conn, client_online, msg_queue, debug
	
	if debug: print('[QUEUE]','handler running')
	
	while running and client_online:
		if not msg_queue.empty():
			if debug: print('[QUEUE]','message waiting')
			while client_online and not msg_queue.empty():
				data = msg_queue.get()
				if debug: print('[QUEUE]','message processing',data)
				
				if data[0] == '#':
					m_type = 'MSG'
				else:
					m_type = 'DATA'
				
				if m_type == 'MSG': 
					if not silent: print('[CLIENT]','{}_SEND'.format(m_type), data)
				data += '\r\n'
				try:
					client_conn.sendall(data.encode("utf-8"))
				except BrokenPipeError:
					client_online = False
					break
			
				# wait for response
				time.sleep(0.1)
				client_conn.settimeout(2)
				rec_data = client_conn.recv(1024).decode('utf-8')
				client_conn.settimeout(None)

				is_ack = False
				if rec_data:
					if m_type == 'MSG':
						msg_ack = MSG_ACK_PATTERN.match(rec_data)
						if msg_ack: is_ack = True
					elif m_type == 'DATA':
						if rec_data.rstrip() == '+': is_ack = True
					
					if is_ack:
						if m_type == 'MSG' and debug: print('[CLIENT]','{}_ACK'.format(m_type))
					else:
						if not silent: print('[CLIENT]','{}_NAK : invalid response'.format(m_type),rec_data)
					
					continue
				else:
					if not silent: print('[CLIENT]','not answered - {} dropped'.format(m_type))
					client_online = False
					break

				time.sleep(0.1)

			if not client_online:
				if not silent: print('[QUEUE]','client gone offline')
			
			if client_online and debug: print('[QUEUE]','no data')
		
		time.sleep(0.1)
	
	if debug: print('[QUEUE]','handler stopped')
	return False

def read_pipe():
	global running, server_message_pipe, msq_queue, debug
	
	try:
		os.mkfifo(server_message_pipe)
		if not silent: print('[PIPE]','ready')
	except OSError as e:
		if e.errno == 17:
			if debug: print('[PIPE]','named-pipe already there ...')
		else:
			print('[PIPE]',server_message_pipe,'ERROR:',e.errno)

	while running:
		with open(server_message_pipe) as fifo:
			while running:
				data = fifo.readline()
				if len(data) == 0:
					if debug: print('[PIPE]','probably closed ...')
					fifo.close()
					break
				if debug: print('[PIPE]','DATA:',data)
				
				if data:
					msg_data = MSG_PATTERN.match(data)
					if msg_data:
						m_type = int(msg_data[1])
						m_speed = int(msg_data[2])
						m_ric = int(msg_data[3])
						m_function = int(msg_data[4])
						message = msg_data[5]
						if not silent: print('[PIPE]','MSG:',m_type,m_speed,m_ric,m_function,message)
						m_send = check_history(m_ric,message)
						if debug: print('[PIPE]', 'check MSG in history - send: ',m_send)
						if m_send:
							msg_queue.put(make_message(m_type,m_speed,m_ric,m_function,message))
						else: 
							if not silent: print('[PIPE]', 'MSG in blocktime - dropped',m_send)
					else:
						if not silent: print('[PIPE]','received invalid message',data)
				else:
					if debug: print('pipe no data')
		if debug: print('[PIPE]','closed!')
	
	return False

def read_socket():
	global running, server_message_socket, msg_queue, debug
	
	if os.path.exists(server_message_socket):
		os.remove(server_message_socket)

	unix_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	unix_socket.bind(server_message_socket)
	if not silent: print('[SOCK]','ready')
	unix_socket.listen(1)
	while running:
		unix_socket.settimeout(3)
		try:
			unix_socket_conn, addr = unix_socket.accept()
		except socket.timeout:
			continue
		except:
			raise
		unix_socket.settimeout(None)
		if debug: print('[SOCK]','connect',addr)
		while running:
			try:
				unix_socket_conn.settimeout(2)
				data = unix_socket_conn.recv(1024).decode('utf-8')
				unix_socket_conn.settimeout(None)
				if data:
					if debug: print('[SOCK]','received data',data)
					msg_data = MSG_PATTERN.match(data)
					
					if msg_data:
						m_type = int(msg_data[1])
						m_speed = int(msg_data[2])
						m_ric = int(msg_data[3])
						m_function = int(msg_data[4])
						message = msg_data[5]
						if not silent: print('[SOCK]','MSG:',m_type,m_speed,m_ric,m_function,message)
						m_send = check_history(m_ric,message)
						if debug: print('[SOCK]', 'check MSG in history - send: ',m_send)
						if m_send:
							msg_queue.put(make_message(m_type,m_speed,m_ric,m_function,message))
						else: 
							if not silent: print('[SOCK]', 'MSG in blocktime - dropped',m_send)
					else:
						if not silent: print('[SOCK]','received invalid message',data)
					
					if debug: print('[SOCK]','MSG ACK')
					unix_socket_conn.sendall('+\r\n'.encode('utf-8'))
				else:
					if debug: print('[SOCK]','close')
					unix_socket_conn.close()
			except:
				break
			time.sleep(1)
		
		time.sleep(1)
	
	unix_socket.shutdown(socket.SHUT_RDWR)
	unix_socket.close()
	return False
	
def clean_history():
	global msg_history, msg_blocktime
	#walk throug msg-history and clean outdates messages
	
	now = int(time.time())
	removed = 0
	for msg,ts in msg_history.copy().items():
		if ts+msg_blocktime <= now:
			msg_history.pop(msg)
			removed += 1
			if debug: print('[dau_core]','clean history - outdated msg',msg,ts,'removed')
	
	if debug: print('[dau_core]','clean history - removed',removed)
	return

def check_history(ric,message):
	global msg_history, msg_blocktime
	
	new_msg = '{:07}:{}'.format(int(ric),message)
	now = int(time.time())
	
	if new_msg in msg_history:
		#check time
		if msg_history[new_msg] + msg_blocktime <= now:
			if debug: print('[dau_core]','msg_history MSG outdated - will sent')
			result =  True
		else:
			if debug: print('[dau_core]','msg_history MSG in blocktime', msg_history[new_msg]+msg_blocktime, now)
			#should we reset blocktime?
			result =  False
	else:
		if debug: print('[dau_core]','msg_history MSG . will sent')
		result = True
	
	if result:
		msg_history[new_msg] = now

	return result

def signal_handler(signum,frame):
	global running, server_online, client_online, core_running, debug
	
	# SIGTERM, SIGKILL
	
	if signum == signal.SIGTERM:
		if not silent: print('[dau_core]','SIGTERM received ...')
		clean_exit()

	return

def clean_exit():
	global running, server_online, client_online, core_running, debug, server
	
	print('[dau_core]','request shutdown ...')
	
	running = False
	core_running = False
	client_online = False
	server_online = False
	
	if debug: print('[dau_core]','closing server ...')
	try:
		client_conn.close()
	except:
		pass
	
	server.shutdown(socket.SHUT_RDWR)
	server.close()

	if debug: print('[dau_core]','waiting for QUEUE ...')
	msg_queue.queue.clear()
	try:
		queue_handle.join(5)
	except:
		pass
	
	if use_message_socket:
		if debug: print('[dau_core]','waiting for SOCK ...')
		sock_reader.join(5)
		if not silent: print('[dau_core]','SOCK closed')
	if use_message_pipe:
		if debug: print('[dau_core]','waiting for PIPE ...')
		pipe_reader.join(5)
		if not silent: print('[dau_core]','PIPE closed')
		try:
			if debug: print('[dau_core]','removing PIPE ...')
			os.unlink(server_message_pipe)
		except:
			pass
	
	if debug: print('[dau_core]','ready to exit')
	
	return


# register sig_handle
signal.signal(signal.SIGTERM, signal_handler)

# init message-queue
if debug: print('[dau_core]','init message queue ...')
msg_queue = Queue()

# init fifo unix socket
if use_message_socket:
	if debug: print('[dau_core]','init SOCK ...')
	sock_reader = Thread(target=read_socket, name='SOCK')
	sock_reader.daemon = True
	sock_reader.start()

# init fifo named pipe
if use_message_pipe:
	if debug: print('[dau_core]','init PIPE ...')
	pipe_reader = Thread(target=read_pipe, name='PIPE')
	pipe_reader.daemon = True
	pipe_reader.start()

# init server
if debug: print('[dau_core]','init dapnet_core ...')
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

for i in range(0,bind_max_try+1):
	try:
		if running:
			server.bind((tcp_address,tcp_port))
			break
	except OSError as e:
		if e.errno == 98 and i < bind_max_try:
			if not silent: print('[CLIENT]','address in use - retry ...',i+1)
			time.sleep(6)
		else:
			raise

server.listen(1)
if not silent: print('[CLIENT]','listen',tcp_address,tcp_port)
server_online = True

try:
	while server_online:
		client_conn, client_address = server.accept()
		print('[CLIENT]','connected',client_address)
		client_online = True
		
		while client_online:
			msg_queue.queue.clear()
			client_conn.settimeout(2)
			data = client_conn.recv(1024).decode('utf-8')
			client_conn.settimeout(None)
			if debug: print('[CLIENT]','received', data)
			
			# Handshake
			login = LOGIN_PATTERN.match(data)
			login_type = login.group(1)
			login_version = login.group(2)
			login_callsign = login.group(3)
			login_key = login.group(4)
			if not silent: print('[CLIENT]','LOGIN:',login_type,login_version,login_callsign,login_key)
			
			# time_sync
			for x in range(0,4):
				if not silent: print('[CLIENT]','TIME_SYNC',x)
				send_data('2:{:04x}'.format(x),False,True)
				
				# erwarte 2:0000:0000
				time.sleep(0.1)
				data = client_conn.recv(1024).decode('utf-8')
				for x in ['\r\n','\r']:
					data = data.replace(x,'')
				time_sync = TIME_PATTERN.match(data)
				if time_sync:
					if debug: print('[CLIENT]','TIME_SYNC',x,'received',time_sync[1],time_sync[2])
				else:
					if not silent: print('[CLIENT]','TIME_SYNC',x,'received invalid response',data)
			
			# ack time_sync
			if not silent: print('[CLIENT]','TIME_SYNC ACK')
			send_data('3:+0000',True,True)
			
			# send slots
			if not silent: print('[CLIENT]','SET_TIMESLOTS',client_slots)
			send_data('4:'+client_slots,True,True)
			
			# main-queue
			if not silent: print('[dau_core]','init client loop')

			core_timer = 0
			last_msg = 0
			last_minute = datetime.datetime.now().minute
			last_beacon = 0
			core_running = True

			if not silent: print('[CLIENT]','BEACON',client_callsign)
			msg_queue.put(make_message(6,1,8,3,client_callsign))
			
			if client_online:
				queue_handle = Thread(target=send_queue, name='QUEUE')
				queue_handle.daemon = True
				queue_handle.start()
			
			while core_running and client_online:
				core_timer += 1
				if core_timer == (core_ping*2):	#core runs 0.5 secs > *2
					msg_queue.put('3:+0000')
					core_timer = 0

				minute = datetime.datetime.now().minute

				# send time-messages & clean msg_history
				if minute != last_minute:
					last_minute = minute
					if (last_minute % 2) == 0 and send_time_utc:
						#gerade minute = UTC
						if debug: print('[CLIENT]','SKYPER_TIME')
						msg_queue.put(make_message(5,1,2504,0,time_skyper()))
						if debug: print('[CLIENT]','SWISSPHONE_TIME')
						msg_queue.put(make_message(6,1,208,3,time_swissphone()))
						if debug: print('[CLIENT]','ALPHAPOC_TIME')
						msg_queue.put(make_message(6,1,224,3,time_alphapoc()))
					elif send_time_local:
						#ungerade minute = Lokalzeiten
						if debug: print('[CLIENT]','SWISSPHONE_LOCALTIME')
						msg_queue.put(make_message(6,1,200,3,time_swissphone(True)))
						if debug: print('[CLIENT]','ALPHAPOC_LOCALTIME')
						msg_queue.put(make_message(6,1,216,3,time_alphapoc(True)))
					
					#cleanup msg_history
					clean_history()
				
				#send transmitter beacon
				if last_beacon + 10 == minute:
					last_beacon = minute
					if not silent: print('[CLIENT]','BEACON',client_callsign)
					msg_queue.put(make_message(6,1,8,3,client_callsign))
				
				time.sleep(0.5)
			
			if not client_online:
				print('[CLIENT]','disconnected',client_address)

except KeyboardInterrupt:
	print('[dau_core]','user interrupt CTRL-C')
	clean_exit()

if debug: print('[dau_core]','cleanly closed !')
sys.exit(0)
