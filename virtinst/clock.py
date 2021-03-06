#
# Copyright 2010, 2013 Red Hat, Inc.
# Cole Robinson <crobinso@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.

from virtinst.xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _ClockTimer(XMLBuilder):
    _XML_ROOT_NAME = "timer"

    name = XMLProperty("./@name")
    present = XMLProperty("./@present", is_yesno=True)
    tickpolicy = XMLProperty("./@tickpolicy")


class Clock(XMLBuilder):
    _XML_ROOT_NAME = "clock"

    TIMER_NAMES = ["platform", "pit", "rtc", "hpet", "tsc", "kvmclock"]

    offset = XMLProperty("./@offset")
    timers = XMLChildProperty(_ClockTimer)

    def add_timer(self):
        obj = _ClockTimer(self.conn)
        self._add_child(obj)
        return obj
    def remove_timer(self, obj):
        self._remove_child(obj)
