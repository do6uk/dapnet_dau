# dapnet_dau
experimental dapnet repeater software

What is it?

A peace of software which will turn an linux-device in a DAPNET-Repeater. You will need some RX-Hardware which is supported by multimon-ng (e.g. RTL-SDR or hardware-RX with audio-device) and a DAPNET-transmitter (e.g. mmdvm with DAPNETGateway or hardware-TX with Unipager).

* dapnet_sock.py will parse and prepare messages decoded by multimon-ng
* dapnet_dau.py will act as "core" to interact with your transmitter (mmdvm or Unipager)
* rtl_multimon_sock.sh is an example how to setup the receiving part with RTL-SDR and multimon-ng

How does it work?

dapnet_sock.py parses the output of multimon-ng ignoring messages with blacklisted ric. The messages are cleaned up and will be pushed to an unix_socket opened by the fake-core dapnet_dau.py.

dapnet_dau.py is a fake-core and hopely behaves like the original DAPNET-core after you configured it in the script - there is no config-file.
After starting at cli, it is opening a unix_socket to collect received messages from dapnet_sock.py and will open a tcp-socket to connect one local transmitter.
Your transmitter will get its timeslots you have defined in the script. In main loop it generates time-messages and the transmitter beacon like the original core.
Whenever messages are in queue they will be imediatly passed to transmitter.

dapnet_dau.py has option to read from named-pipe if you have activated in the code. Over the pipe you can manually inject messages in format 
type:speed:ric:function:text e.g. 6:1:8:3:de0abc will send alphanumeric message 'de0abc' with 1200 baud to ric 8 function 3

What not works!

dapnet_sock.py will not check, if messages are received duplicated from multiple transmitters and pass them in the fake-core.
dapnet_dau.py will not generaty rubric contect itself - it will only forward received messages.
dapnet_dau.py has no api to inject messages or control the core.


and now ... Feel free to play with it.
