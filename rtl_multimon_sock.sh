#!/bin/bash

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

rtl_fm -E dc -f 439.9875M -s 22050 - | multimon-ng -a POCSAG1200 -t raw /dev/stdin | ./dapnet_sock.py
