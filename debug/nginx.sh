#!/bin/sh
killall nginx fcgiwrap > /dev/null
rm -f fcgiwrap.socket
/usr/bin/env printf 'fastcgi_param SCRIPT_FILENAME "%q/../zzcxz.cgi"; fastcgi_pass "unix:%q/fcgiwrap.socket";' "$(pwd)" "$(pwd)" > /tmp/fastcgi_conf;
fcgiwrap -s unix:"$(pwd)"/fcgiwrap.socket &
nginx -p "$(pwd)" -c nginx.conf 
