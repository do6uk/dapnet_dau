20221205
fix	message-counter overflow - counter did not reset after 0xFF
fix	messages sent by dapnet_dau could be received by dapnet_sock and built a loop
change	reduced output at console - use debug = True to see more
change	removing named_pipe on (clean) exit
add	msg_history in dapnet_dau will prevent sending repeated same ric and message in blocktime
add	bind in dapnet_dau will retry if addr_in_use
add	dropping msg-queue at dapnet_sock if core is not responding on 3 reconnects
add	listening on signal SIGTERM to shutdown both scripts if run as service
add	silent-mode to supress most output at cli
