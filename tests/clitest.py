# Copyright (C) 2013 Red Hat, Inc.
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

import atexit
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import unittest
import StringIO

import virtinst.cli
from virtinst import support

from tests import virtinstall, virtimage, virtclone, virtconvert
from tests import utils

os.environ["VIRTCONV_TEST_NO_DISK_CONVERSION"] = "1"
os.environ["LANG"] = "en_US.UTF-8"

# Used to ensure consistent SDL xml output
os.environ["HOME"] = "/tmp"
os.environ["DISPLAY"] = ":3.4"

_defaultconn = utils.open_testdefault()

# Location
image_prefix = "/tmp/__virtinst_cli_"
xmldir = "tests/cli-test-xml"
treedir = "%s/faketree" % xmldir
vcdir = "%s/virtconv" % xmldir
ro_dir = image_prefix + "clitest_rodir"
ro_img = "%s/cli_exist3ro.img" % ro_dir
ro_noexist_img = "%s/idontexist.img" % ro_dir
compare_xmldir = "%s/compare" % xmldir
virtconv_out = "/tmp/__virtinst_tests__virtconv-outdir"

# Images that will be created by virt-install/virt-clone, and removed before
# each run
new_images = [
    image_prefix + "new1.img",
    image_prefix + "new2.img",
    image_prefix + "new3.img",
    image_prefix + "exist1-clone.img",
    image_prefix + "exist2-clone.img",
]

# Images that are expected to exist before a command is run
exist_images = [
    image_prefix + "exist1.img",
    image_prefix + "exist2.img",
    ro_img,
]

# Images that need to exist ahead of time for virt-image
virtimage_exist = ["/tmp/__virtinst__cli_root.raw"]

# Images created by virt-image
virtimage_new = ["/tmp/__virtinst__cli_scratch.raw"]

# virt-convert output dirs
virtconv_dirs = [virtconv_out]

exist_files = exist_images + virtimage_exist
new_files   = new_images + virtimage_new + virtconv_dirs
clean_files = (new_images + exist_images +
               virtimage_exist + virtimage_new + virtconv_dirs + [ro_dir])

promptlist = []

test_files = {
    'TESTURI'           : utils.testuri,
    'DEFAULTURI'        : utils.defaulturi,
    'REMOTEURI'         : utils.uriremote,
    'KVMURI'            : utils.urikvm,
    'XENURI'            : utils.urixencaps,
    'XENIA64URI'        : utils.urixenia64,
    'LXCURI'            : utils.urilxc,
    'CLONE_DISK_XML'    : "%s/clone-disk.xml" % xmldir,
    'CLONE_STORAGE_XML' : "%s/clone-disk-managed.xml" % xmldir,
    'CLONE_NOEXIST_XML' : "%s/clone-disk-noexist.xml" % xmldir,
    'IMAGE_XML'         : "%s/image.xml" % xmldir,
    'IMAGE_NOGFX_XML'   : "%s/image-nogfx.xml" % xmldir,
    'NEWIMG1'           : new_images[0],
    'NEWIMG2'           : new_images[1],
    'NEWIMG3'           : new_images[2],
    'EXISTIMG1'         : exist_images[0],
    'EXISTIMG2'         : exist_images[1],
    'ROIMG'             : ro_img,
    'ROIMGNOEXIST'      : ro_noexist_img,
    'POOL'              : "default-pool",
    'VOL'               : "testvol1.img",
    'DIR'               : os.getcwd(),
    'TREEDIR'           : treedir,
    'MANAGEDEXIST1'     : "/dev/default-pool/testvol1.img",
    'MANAGEDEXIST2'     : "/dev/default-pool/testvol2.img",
    'MANAGEDEXISTUPPER' : "/dev/default-pool/UPPER",
    'MANAGEDNEW1'       : "/dev/default-pool/clonevol",
    'MANAGEDNEW2'       : "/dev/default-pool/clonevol",
    'MANAGEDDISKNEW1'   : "/dev/disk-pool/newvol1.img",
    'COLLIDE'           : "/dev/default-pool/collidevol1.img",
    'SHARE'             : "/dev/default-pool/sharevol.img",

    'VIRTCONV_OUT'      : "%s/test.out" % virtconv_out,
    'VC_IMG1'           : "%s/virtimage/test1.virt-image" % vcdir,
    'VC_IMG2'           : "tests/image-xml/image-format.xml",
    'VMX_IMG1'          : "%s/vmx/test1.vmx" % vcdir,
}



######################
# Test class helpers #
######################


class Command(object):
    """
    Instance of a single cli command to test
    """
    SKIP = -123

    def __init__(self, cmd):
        self.cmdstr = cmd % test_files
        self.check_success = True
        self.compare_file = None
        self.support_check = None

        app, opts = self.cmdstr.split(" ", 1)
        self.app = app
        self.argv = [os.path.abspath(app)] + shlex.split(opts)

    def _launch_command(self):
        logging.debug(self.cmdstr)

        app = self.argv[0]
        conn = None

        for idx in reversed(range(len(self.argv))):
            if self.argv[idx] == "--connect":
                conn = utils.openconn(self.argv[idx + 1])
                break

        if not conn and "virt-convert" not in app:
            raise RuntimeError("couldn't parse URI from command %s" %
                               self.argv)

        skipmsg = self._skip_msg(conn)
        if skipmsg is not None:
            return (self.SKIP, skipmsg)

        oldstdout = sys.stdout
        oldstderr = sys.stderr
        oldargv = sys.argv
        try:
            out = StringIO.StringIO()
            sys.stdout = out
            sys.stderr = out
            sys.argv = self.argv

            try:
                if app.count("virt-install"):
                    ret = virtinstall.main(conn=conn)
                elif app.count("virt-clone"):
                    ret = virtclone.main(conn=conn)
                elif app.count("virt-image"):
                    ret = virtimage.main(conn=conn)
                elif app.count("virt-convert"):
                    ret = virtconvert.main()
            except SystemExit, sys_e:
                ret = sys_e.code

            if ret != 0:
                ret = -1
            outt = out.getvalue()
            if outt.endswith("\n"):
                outt = outt[:-1]
            return (ret, outt)
        finally:
            sys.stdout = oldstdout
            sys.stderr = oldstderr
            sys.argv = oldargv


    def _get_output(self):
        try:
            for i in new_files:
                if os.path.isdir(i):
                    shutil.rmtree(i)
                elif os.path.exists(i):
                    os.unlink(i)

            code, output = self._launch_command()

            logging.debug(output + "\n")
            return code, output
        except Exception, e:
            return (-1, "".join(traceback.format_exc()) + str(e))

    def _skip_msg(self, conn):
        if self.support_check is None:
            return
        if conn is None:
            raise RuntimeError("support_check is not None, but conn is None")
        if conn.check_support(self.support_check):
            return
        return "skipped"

    def run(self, tests):
        filename = self.compare_file
        err = None

        try:
            code, output = self._get_output()
            if code == self.SKIP:
                tests.skipTest(output)
                return

            if bool(code) == self.check_success:
                raise AssertionError(
                    ("Expected command to %s, but it didn't.\n" %
                     (self.check_success and "pass" or "fail")) +
                     ("Command was: %s\n" % self.cmdstr) +
                     ("Error code : %d\n" % code) +
                     ("Output was:\n%s" % output))

            if filename:
                # Generate test files that don't exist yet
                if not os.path.exists(filename):
                    file(filename, "w").write(output)

                utils.diff_compare(output, filename)

        except AssertionError, e:
            err = self.cmdstr + "\n" + str(e)

        if err:
            tests.fail(err)


class PromptCheck(object):
    """
    Individual question/response pair for automated --prompt tests
    """
    def __init__(self, prompt, response=None):
        self.prompt = prompt
        self.response = response
        if self.response:
            self.response = self.response % test_files

    def check(self, proc):
        out = proc.stdout.readline()

        if not out.count(self.prompt):
            out += "\nContent didn't contain prompt '%s'" % (self.prompt)
            return False, out

        if self.response:
            proc.stdin.write(self.response + "\n")

        return True, out


class PromptTest(Command):
    """
    Fully automated --prompt test
    """
    def __init__(self, cmdstr):
        Command.__init__(self, cmdstr)

        self.prompt_list = []

    def add(self, *args, **kwargs):
        self.prompt_list.append(PromptCheck(*args, **kwargs))

    def _launch_command(self):
        proc = subprocess.Popen(self.argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)

        out = "Running %s\n" % self.cmdstr

        for p in self.prompt_list:
            ret, content = p.check(proc)
            out += content
            if not ret:
                # Since we didn't match output, process might be hung
                proc.kill()
                break

        exited = False
        for ignore in range(30):
            if proc.poll() is not None:
                exited = True
                break
            time.sleep(.1)

        if not exited:
            proc.kill()
            out += "\nProcess was killed by test harness"

        return proc.wait(), out


class _CategoryProxy(object):
    def __init__(self, app, name):
        self._app = app
        self._name = name

    def add_valid(self, *args, **kwargs):
        return self._app.add_valid(self._name, *args, **kwargs)
    def add_invalid(self, *args, **kwargs):
        return self._app.add_invalid(self._name, *args, **kwargs)
    def add_compare(self, *args, **kwargs):
        return self._app.add_compare(self._name, *args, **kwargs)


class App(object):
    def __init__(self, appname):
        self.appname = appname
        self.categories = {}
        self.cmds = []

    def _default_args(self, cli, iscompare):
        args = ""
        if not iscompare:
            args = "--debug"

        if self.appname != "virt-convert" and not iscompare:
            if "--connect " not in cli:
                args += " --connect %(TESTURI)s"

        if self.appname in ["virt-install"]:
            if "--name " not in cli:
                args += " --name foobar"
            if "--ram " not in cli:
                args += " --ram 64"

        if iscompare:
            if self.appname == "virt-install":
                if (not cli.count("--print-xml") and
                    not cli.count("--print-step") and
                    not cli.count("--quiet")):
                    args += " --print-step all"

            elif self.appname == "virt-image":
                if not cli.count("--print"):
                    args += " --print"

            elif self.appname == "virt-clone":
                if not cli.count("--print-xml"):
                    args += " --print-xml"

            if self.appname != "virt-convert" and not "--connect " in cli:
                args += " --connect %s" % utils.fakeuri

        return args


    def add_category(self, catname, default_args):
        self.categories[catname] = default_args
        return _CategoryProxy(self, catname)

    def _add(self, catname, testargs, valid, compfile, support_check=None):
        args = self.categories[catname] + " " + testargs
        args = self._default_args(args, bool(compfile)) + " " + args
        cmdstr = "./%s %s" % (self.appname, args)

        cmd = Command(cmdstr)
        cmd.check_success = valid
        if compfile:
            cmd.compare_file = "%s/%s.xml" % (compare_xmldir, compfile)
        cmd.support_check = support_check
        self.cmds.append(cmd)

    def add_valid(self, cat, args, **kwargs):
        self._add(cat, args, True, None, **kwargs)
    def add_invalid(self, cat, args, **kwargs):
        self._add(cat, args, False, None, **kwargs)
    def add_compare(self, cat, args, compfile, **kwargs):
        self._add(cat, args, not compfile.endswith("-fail"),
                  compfile, **kwargs)



#
# The test matrix
#
# add_valid: A test that should pass
# add_invalid: A test that should fail
# add_compare: Get the generated XML, and compare against the passed filename
#              in tests/clitest-xml/compare/
#

vinst = App("virt-install")
c = vinst.add_category("cpuram", "--hvm --nographics --noautoconsole --nodisks --pxe")
c.add_valid("--vcpus 32")  # Max VCPUS
c.add_valid("--vcpus 4 --cpuset=1,3-5")  # Cpuset
c.add_valid("--vcpus 4 --cpuset=1,3-5,")  # Cpuset with trailing comma
c.add_valid("--vcpus 4 --cpuset=auto")  # Cpuset with trailing comma
c.add_valid("--ram 100000000000")  # Ram overcommit
c.add_valid("--vcpus 4,cores=2,threads=2,sockets=2")  # Topology
c.add_valid("--vcpus 4,cores=1")  # Topology auto-fill
c.add_valid("--vcpus sockets=2,threads=2")  # Topology only
c.add_valid("--cpu somemodel")  # Simple --cpu
c.add_valid("--cpu foobar,+x2apic,+x2apicagain,-distest,forbid=foo,forbid=bar,disable=distest2,optional=opttest,require=reqtest,match=strict,vendor=meee")  # Crazy --cpu
c.add_valid("--numatune 1,2,3,5-7,^6")  # Simple --numatune
c.add_valid("--numatune 1-3,4,mode=strict")  # More complex, parser should do the right thing here
c.add_compare("--connect %(DEFAULTURI)s --cpuset auto --vcpus 2", "cpuset-auto")  # --cpuset=auto actually works
c.add_invalid("--vcpus 32 --cpuset=969-1000")  # Bogus cpuset
c.add_invalid("--vcpus 32 --cpuset=autofoo")  # Bogus cpuset
c.add_invalid("--cpu host")  # --cpu host, but no host CPU in caps
c.add_invalid("--clock foo_tickpolicy=merge")  # Unknown timer


c = vinst.add_category("smartcard", "--noautoconsole --nodisks --pxe")
c.add_valid("--smartcard host")  # --smartcard host
c.add_valid("--smartcard none")  # --smartcard none,
c.add_valid("--smartcard passthrough,type=spicevmc")  # --smartcard mode with type
c.add_invalid("--smartcard passthrough,type=foo")  # Invalid type


c = vinst.add_category("tpm", "--noautoconsole --nodisks --pxe")
c.add_valid("--tpm passthrough")  # --tpm passthrough
c.add_valid("--tpm passthrough,model=tpm-tis")  # --tpm backend type with model
c.add_valid("--tpm passthrough,model=tpm-tis,path=/dev/tpm0")  # --tpm backend type with model and device path
c.add_invalid("--tpm passthrough,model=foo")  # Invalid model


c = vinst.add_category("rng", "--noautoconsole --nodisks --pxe")
c.add_valid("--rng random,device=/dev/random")  # random device backend
c.add_valid("--rng /dev/random")  # random device backend, short form
c.add_invalid("--rng /FOO/BAR")  # random device backend, short form, invalid device
c.add_valid("--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=tcp")  # egd backend
c.add_valid("--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=tcp,backend_mode=bind")  # egd backend, bind mode
c.add_invalid("--rng foo,backend_host=127.0.0.1,backend_service=8000,backend_mode=connect")  # invalid type
c.add_invalid("--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=udp,backend_mode=bind")  # invalid only bind for udp
c.add_valid("--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=tcp,backend_mode=bind")  # egd backend, bind mode
c.add_valid("--rng egd,backend_host=127.0.0.1,backend_service=8000,backend_type=udp,backend_mode=bind,backend_connect_host=foo,backend_connect_service=708")  # egd backend, udp mode bind, bind backend mode


c = vinst.add_category("panic", "--noautoconsole --nodisks --pxe")
c.add_valid("--panic default")  # panic device with default setting
c.add_valid("--panic iobase=0x506")  # panic device with iobase=0x506
c.add_valid("--panic iobase=507")  # panic device with iobase=0x507


c = vinst.add_category("xen", "--connect %(XENURI)s --noautoconsole")
c.add_compare("--disk %(EXISTIMG1)s --import", "xen-default")  # Xen default
c.add_compare("--disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-pv")  # Xen PV
c.add_compare("--disk %(EXISTIMG1)s --cdrom %(EXISTIMG1)s --livecd --hvm", "xen-hvm")  # Xen HVM
c.add_compare("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --import", "xen-ia64-default")  # ia64 default
c.add_compare("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --paravirt", "xen-ia64-pv")  # ia64 pv
c.add_compare("--connect %(XENIA64URI)s --disk %(EXISTIMG1)s --location %(TREEDIR)s --hvm", "xen-ia64-hvm")  # ia64 hvm
c.add_valid("--nodisks --cdrom %(EXISTIMG1)s --livecd --hvm")  # HVM
c.add_valid("--nodisks --boot hd --paravirt")  # PV
c.add_valid("--nodisks --boot hd --paravirt --arch i686")  # 32 on 64 xen


c = vinst.add_category("kvm", "--connect %(KVMURI)s --noautoconsole")
c.add_compare("--os-variant fedora20 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --cpu host --channel none --console none", "kvm-f14-url")  # F14 Directory tree URL install with extra-args
c.add_compare("--os-variant fedora20 --disk %(NEWIMG1)s,size=.01 --location %(TREEDIR)s --extra-args console=ttyS0 --quiet", "quiet-url")  # Quiet URL install should make no noise
c.add_compare("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound --controller usb", "kvm-win2k3-cdrom")  # HVM windows install with disk
c.add_compare("--os-variant fedora20 --nodisks --boot hd --paravirt", "kvm-xenner")  # xenner
c.add_compare("--os-variant fedora20 --nodisks --boot cdrom --virt-type qemu --cpu Penryn", "qemu-plain")  # plain qemu
c.add_compare("--os-variant fedora20 --nodisks --boot network --nographics --arch i686", "qemu-32-on-64")  # 32 on 64
c.add_compare("--os-variant fedora20 --nodisks --boot fd --graphics spice --machine pc", "kvm-machine")  # kvm machine type 'pc'
c.add_compare("--os-variant fedora20 --nodisks --boot fd --graphics sdl --arch sparc --machine SS-20", "qemu-sparc")  # exotic arch + machine type
c.add_compare("--arch armv7l --machine vexpress-a9 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,dtb=/f19-arm.dtb,kernel_args=\"console=ttyAMA0 rw root=/dev/mmcblk0p3\" --disk %(EXISTIMG1)s --nographics", "arm-vexpress-plain", support_check=support.SUPPORT_CONN_DISK_SD)
c.add_compare("--arch armv7l --machine vexpress-a15 --boot kernel=/f19-arm.kernel,initrd=/f19-arm.initrd,dtb=/f19-arm.dtb,kernel_args=\"console=ttyAMA0 rw root=/dev/vda3\" --disk %(EXISTIMG1)s --nographics --os-variant fedora19", "arm-vexpress-f19", support_check=support.SUPPORT_CONN_VIRTIO_MMIO)
c.add_compare("--arch ppc64 --machine pseries --boot network --disk %(EXISTIMG1)s --os-variant fedora20", "ppc64-pseries-f20")
c.add_valid("--cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --sound")  # HVM windows install with disk
c.add_valid("--os-variant fedora20 --file %(EXISTIMG1)s --location %(TREEDIR)s --extra-args console=ttyS0 --sound")  # F14 Directory tree URL install with extra-args
c.add_invalid("--nodisks --boot network --machine foobar")  # Unknown machine type
c.add_invalid("--nodisks --boot network --arch mips --virt-type kvm")  # Invalid domain type for arch
c.add_invalid("--nodisks --boot network --paravirt --arch mips")  # Invalid arch/virt combo


c = vinst.add_category("misc", "--nographics --noautoconsole")
c.add_valid("--panic=? --disk=?")  # Make sure introspection doesn't blow up
c.add_compare("", "noargs-fail")  # No arguments
c.add_compare("--hvm --nodisks --pxe --print-step all", "simple-pxe")  # Diskless PXE install
c.add_compare("--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --vcpus cores=4 --controller usb,model=none", "w2k3-cdrom")  # HVM windows install with disk
c.add_compare("""--hvm --pxe \
--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0 \
--controller usb,model=ich9-uhci1,address=0:0:4.0,index=0,master=0 \
--controller usb,model=ich9-uhci2,address=0:0:4.1,index=0,master=2 \
--controller usb,model=ich9-uhci3,address=0:0:4.2,index=0,master=4 \
--disk %(MANAGEDEXISTUPPER)s,cache=writeback,io=threads,perms=sh,serial=WD-WMAP9A966149 \
--disk %(NEWIMG1)s,sparse=false,size=.001,perms=ro,error_policy=enospace \
--disk device=cdrom,bus=sata \
--serial tcp,host=:2222,mode=bind,protocol=telnet \
--filesystem /source,/target,mode=squash \
--network user,mac=12:34:56:78:11:22 \
--network bridge=foobar,model=virtio \
--network type=direct,source=eth5,source_mode=vepa,target=mytap12 \
--channel spicevmc \
--smartcard passthrough,type=spicevmc \
--tpm /dev/tpm0 \
--panic default \
--security type=static,label='system_u:object_r:svirt_image_t:s0:c100,c200',relabel=yes \
--numatune \\"1-3,5\\",mode=preferred \
--boot loader=/foo/bar \
--host-device net_00_1c_25_10_b1_e4 \
--features acpi=off,eoi=on,privnet=on,hyperv_spinlocks=on,hyperv_spinlocks_retries=1234 \
--clock offset=localtime,hpet_present=no,rtc_tickpolicy=merge \
""", "many-devices")  # Lots of devices
c.add_valid("--hvm --disk path=virt-install,device=cdrom")  # Specifying cdrom media via --disk
c.add_valid("--hvm --import --disk path=virt-install")  # FV Import install
c.add_valid("--hvm --import --disk path=virt-install --prompt --force")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--paravirt --import --disk path=virt-install")  # PV Import install
c.add_valid("--paravirt --import --disk path=virt-install --print-xml")  # PV Import install, print single XML
c.add_valid("--hvm --import --disk path=virt-install,device=floppy")  # Import a floppy disk
c.add_valid("--hvm --nodisks --pxe --autostart")  # --autostart flag
c.add_valid("--hvm --nodisks --pxe --description \"foobar & baz\"")  # --description
c.add_valid("--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0")  # HVM windows install with disk
c.add_valid("--hvm --cdrom %(EXISTIMG2)s --file %(EXISTIMG1)s --os-variant win2k3 --wait 0 --print-step 3")  # HVM windows install, print 3rd stage XML
c.add_valid("--hvm --nodisks --pxe --watchdog default")  # --watchdog dev default
c.add_valid("--hvm --nodisks --pxe --watchdog ib700,action=pause")  # --watchdog opts
c.add_valid("--hvm --nodisks --pxe --sound")  # --sound option
c.add_valid("--hvm --nodisks --pxe --soundhw default --soundhw ac97")  # --soundhw option
c.add_valid("--hvm --nodisks --pxe --security type=dynamic")  # --security dynamic
c.add_valid("--hvm --nodisks --pxe --security label=foobar.label,relabel=yes")  # --security implicit static
c.add_valid("--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3,type=static,relabel=no")  # --security static with commas 1
c.add_valid("--hvm --nodisks --pxe --security label=foobar.label,a1,z2,b3")  # --security static with commas 2
c.add_valid("--hvm --pxe --filesystem /foo/source,/bar/target")  # --filesystem simple
c.add_valid("--hvm --pxe --filesystem template_name,/,type=template")  # --filesystem template
c.add_valid("--hvm --nodisks --nonetworks --cdrom %(EXISTIMG1)s")  # no networks
c.add_valid("--hvm --nodisks --pxe --memballoon virtio")  # --memballoon use virtio
c.add_valid("--hvm --nodisks --pxe --memballoon none")  # --memballoon disabled
c.add_invalid("--hvm --nodisks --pxe foobar")  # Positional arguments error
c.add_invalid("--nodisks --pxe --nonetworks")  # pxe and nonetworks
c.add_invalid("--nodisks --pxe --name test")  # Colliding name
c.add_invalid("--hvm --nodisks --pxe --watchdog default,action=foobar")  # Busted --watchdog
c.add_invalid("--hvm --nodisks --pxe --soundhw default --soundhw foobar")  # Busted --soundhw
c.add_invalid("--hvm --nodisks --pxe --security type=foobar")  # Busted --security
c.add_invalid("--paravirt --import --disk path=virt-install --print-step 2")  # PV Import install, no second XML step
c.add_invalid("--hvm --nodisks --pxe --print-xml")  # 2 stage install with --print-xml
c.add_invalid("--hvm --nodisks --pxe --memballoon foobar")  # Busted --memballoon


c = vinst.add_category("char", "--hvm --nographics --noautoconsole --nodisks --pxe")
c.add_valid("--serial pty --parallel null")  # Simple devs
c.add_valid("--serial file,path=/tmp/foo --parallel unix,path=/tmp/foo --parallel null")  # Some with options
c.add_valid("--parallel udp,host=0.0.0.0:1234,bind_host=127.0.0.1:1234")  # UDP
c.add_valid("--serial tcp,mode=bind,host=0.0.0.0:1234")  # TCP
c.add_valid("--parallel unix,path=/tmp/foo-socket")  # Unix
c.add_valid("--serial tcp,host=:1234,protocol=telnet")  # TCP w/ telnet
c.add_valid("--channel pty,target_type=guestfwd,target_address=127.0.0.1:10000")  # --channel guestfwd
c.add_valid("--channel pty,target_type=virtio,name=org.linux-kvm.port1")  # --channel virtio
c.add_valid("--channel pty,target_type=virtio")  # --channel virtio without name=
c.add_valid("--console pty,target_type=virtio")  # --console virtio
c.add_valid("--console pty,target_type=xen")  # --console xen
c.add_invalid("--serial unix")  # Unix with no path
c.add_invalid("--serial null,path=/tmp/foo")  # Path where it doesn't belong
c.add_invalid("--channel pty,target_type=guestfwd")  # --channel guestfwd without target_address


c = vinst.add_category("controller", "--noautoconsole --nodisks --pxe")
c.add_valid("--controller usb,model=ich9-ehci1,address=0:0:4.7")
c.add_valid("--controller usb,model=ich9-ehci1,address=0:0:4.7,index=0")
c.add_valid("--controller usb,model=ich9-ehci1,address=0:0:4.7,index=1")
c.add_valid("--controller usb2 --controller usb3")


c = vinst.add_category("lxc", "--connect %(LXCURI)s --noautoconsole --name foolxc --ram 64")
c.add_compare("", "default")
c.add_compare("--filesystem /source,/", "fs-default")
c.add_compare("--init /usr/bin/httpd", "manual-init")


c = vinst.add_category("graphics", "--noautoconsole --nodisks --pxe")
c.add_valid("--sdl")  # SDL
c.add_valid("--graphics sdl")  # --graphics SDL
c.add_valid("--graphics none")  # --graphics none,
c.add_valid("--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4")  # VNC w/ lots of options
c.add_valid("--graphics vnc,port=5950,listen=1.2.3.4,keymap=ja,password=foo")  # VNC w/ lots of options, new way
c.add_valid("--graphics spice,port=5950,tlsport=5950,listen=1.2.3.4,keymap=ja")  # SPICE w/ lots of options
c.add_valid("--vnc --video vga")  # --video option
c.add_valid("--graphics spice --video qxl")  # --video option
c.add_valid("--vnc --keymap local")  # --keymap local,
c.add_valid("--vnc --keymap none")  # --keymap none
c.add_invalid("--vnc --keymap ZZZ")  # Invalid keymap
c.add_invalid("--vnc --vncport -50")  # Invalid port
c.add_invalid("--graphics spice,tlsport=5")  # Invalid port
c.add_invalid("--graphics vnc --vnclisten 1.2.3.4")  # mixing old and new


c = vinst.add_category("remote", "--connect %(REMOTEURI)s --nographics --noautoconsole")
c.add_valid("--nodisks --pxe")  # Simple pxe nodisks
c.add_valid("--nodisks --cdrom %(MANAGEDEXIST1)s")  # Managed CDROM install
c.add_valid("--pxe --file %(MANAGEDEXIST1)s")  # Using existing managed storage
c.add_valid("--pxe --disk vol=%(POOL)s/%(VOL)s")  # Using existing managed storage 2
c.add_valid("--pxe --disk pool=%(POOL)s,size=.04")  # Creating storage on managed pool
c.add_invalid("--nodisks --location /tmp")  # Use of --location
c.add_invalid("--file %(EXISTIMG1)s --pxe")  # Trying to use unmanaged storage


c = vinst.add_category("network", "--pxe --nographics --noautoconsole --nodisks")
c.add_valid("--mac 22:22:33:44:55:AF")  # Just a macaddr
c.add_valid("--bridge mybr0 --mac 22:22:33:44:55:AF")  # Old bridge w/ mac
c.add_valid("--network bridge:mybr0,model=e1000")  # --network bridge:
c.add_valid("--network network:default --mac RANDOM")  # VirtualNetwork with a random macaddr
c.add_valid("--network network=default,mac=22:00:11:00:11:00")  # Using '=' as the net type delimiter
c.add_valid("--network=network:default,model=e1000 --network=user,model=virtio,mac=22:22:33:44:55:AF")  # several networks
c.add_invalid("--network=FOO")  # Nonexistent network
c.add_invalid("--network=network:default --mac 1234")  # Invalid mac
c.add_invalid("--network user --bridge foo0")  # Mixing bridge and network
c.add_invalid("--mac 22:22:33:12:34:AB")  # Colliding macaddr


c = vinst.add_category("storage", "--pxe --nographics --noautoconsole --hvm")
c.add_valid("--file %(EXISTIMG1)s --nonsparse --file-size 4")  # Existing file, other opts
c.add_valid("--file %(EXISTIMG1)s")  # Existing file, no opts
c.add_valid("--file %(EXISTIMG1)s --file virt-image --file virt-clone")  # Multiple existing files
c.add_valid("--file %(NEWIMG1)s --file-size .00001 --nonsparse")  # Nonexistent file
c.add_valid("--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=writethrough,io=threads")  # Existing disk, lots of opts
c.add_valid("--disk path=%(EXISTIMG1)s,perms=rw")  # Existing disk, rw perms
c.add_valid("--disk path=%(EXISTIMG1)s,device=floppy")  # Existing floppy
c.add_valid("--disk path=%(EXISTIMG1)s")  # Existing disk, no extra options
c.add_valid("--disk pool=%(POOL)s,size=.0001 --disk pool=%(POOL)s,size=.0001")  # Create 2 volumes in a pool
c.add_valid("--disk vol=%(POOL)s/%(VOL)s")  # Existing volume
c.add_valid("--disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s --disk path=%(EXISTIMG1)s,device=cdrom")  # 3 IDE and CD
c.add_valid(" --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi --disk path=%(EXISTIMG1)s,bus=scsi")  # > 16 scsi disks
c.add_valid("--disk path=%(NEWIMG1)s,format=raw,size=.0000001")  # Unmanaged file using format 'raw'
c.add_valid("--disk path=%(MANAGEDNEW1)s,format=raw,size=.0000001")  # Managed file using format raw
c.add_valid("--disk path=%(MANAGEDNEW1)s,format=qcow2,size=.0000001")  # Managed file using format qcow2
c.add_valid("--disk path=%(ROIMG)s,perms=ro")  # Using ro path as a disk with readonly flag
c.add_valid("--disk path=%(ROIMG)s,device=cdrom")  # Using RO path with cdrom dev
c.add_valid("--disk %(EXISTIMG1)s")  # Not specifying path=
c.add_valid("--disk %(NEWIMG1)s,format=raw,size=.0000001")  # Not specifying path= but creating storage
c.add_valid("--disk %(COLLIDE)s --force")  # Colliding storage with --force
c.add_valid("--disk %(SHARE)s,perms=sh")  # Colliding shareable storage
c.add_valid("--disk path=%(EXISTIMG1)s,device=cdrom --disk path=%(EXISTIMG1)s,device=cdrom")  # Two IDE cds
c.add_valid("--disk %(DIR)s,device=floppy")  # Dir with a floppy dev
c.add_valid("--disk %(EXISTIMG1)s,driver_name=qemu,driver_type=qcow2")  # Driver name and type options
c.add_valid("--disk /dev/hda")  # Using a storage pool source as a disk
c.add_valid("--disk pool=default,size=.00001")  # Building 'default' pool
c.add_valid("--disk path=%(EXISTIMG1)s,bus=usb")  # Existing USB disk
c.add_valid("--disk path=%(EXISTIMG1)s,bus=usb,removable=on")  # Existing USB disk as removable
c.add_valid("--disk path=%(EXISTIMG1)s,bus=usb,removable=off")  # Existing USB disk as non-removable
c.add_invalid("--file %(NEWIMG1)s --file-size 100000 --nonsparse")  # Nonexisting file, size too big
c.add_invalid("--file %(NEWIMG1)s --file-size 100000")  # Huge file, sparse, but no prompting
c.add_invalid("--file %(NEWIMG1)s")  # Nonexisting file, no size
c.add_invalid("--file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s --file %(EXISTIMG1)s")  # Too many IDE
c.add_invalid("--file-size .0001")  # Size, no file
c.add_invalid("--disk pool=foopool,size=.0001")  # Specify a nonexistent pool
c.add_invalid("--disk vol=%(POOL)s/foovol")  # Specify a nonexistent volume
c.add_invalid("--disk pool=%(POOL)s")  # Specify a pool with no size
c.add_invalid("--disk path=%(EXISTIMG1)s,perms=ro,size=.0001,cache=FOOBAR")  # Unknown cache type
c.add_invalid("--disk path=%(NEWIMG1)s,format=qcow2,size=.0000001")  # Unmanaged file using non-raw format
c.add_invalid("--disk path=%(MANAGEDDISKNEW1)s,format=raw,size=.0000001")  # Managed disk using any format
c.add_invalid("--disk %(NEWIMG1)s")  # Not specifying path= and non existent storage w/ no size
c.add_invalid("--disk %(COLLIDE)s")  # Colliding storage without --force
c.add_invalid("--disk /dev/default-pool/backingl3.img")  # Colliding storage via backing store
c.add_invalid("--disk %(DIR)s,device=cdrom")  # Dir without floppy
c.add_invalid("--disk %(EXISTIMG1)s,driver_name=foobar,driver_type=foobaz")  # Unknown driver name and type options (as of 1.0.0)
c.add_valid("--disk path=%(EXISTIMG1)s,startup_policy=optional")  # Existing disk, startupPolicy
c.add_invalid("--disk path=%(EXISTIMG1)s,startup_policy=Foo")  # Existing disk, invalid startupPolicy


c = vinst.add_category("redirdev", "--noautoconsole --nographics --nodisks --pxe")
c.add_valid("--redirdev usb,type=spicevmc")
c.add_valid("--redirdev usb,type=tcp,server=localhost:4000")
c.add_valid("--redirdev usb,type=tcp,server=127.0.0.1:4002")  # Different host server


c = vinst.add_category("hostdev", "--noautoconsole --nographics --nodisks --pxe")
c.add_valid("--host-device usb_device_781_5151_2004453082054CA1BEEE")  # Host dev by libvirt name
c.add_valid("--host-device 001.003 --host-device 15:0.1 --host-device 2:15:0.2 --host-device 0:15:0.3 --host-device 0x0781:0x5151,driver_name=vfio")  # Many hostdev parsing types
c.add_invalid("--host-device 1d6b:2")  # multiple USB devices with identical vendorId and productId
c.add_invalid("--host-device pci_8086_2850_scsi_host_scsi_host")  # Unsupported hostdev type
c.add_invalid("--host-device foobarhostdev")  # Unknown hostdev
c.add_invalid("--host-device 300:400")  # Parseable hostdev, but unknown digits


c = vinst.add_category("install", "--nographics --noautoconsole --nodisks")
c.add_valid("--hvm --cdrom %(EXISTIMG1)s")  # Simple cdrom install
c.add_valid("--hvm --cdrom %(MANAGEDEXIST1)s")  # Cdrom install with managed storage
c.add_valid("--hvm --wait 0 --os-variant winxp --cdrom %(EXISTIMG1)s")  # Windows (2 stage) install
c.add_valid("--hvm --pxe --virt-type test")  # Explicit virt-type
c.add_valid("--arch i686 --pxe")  # Explicity fullvirt + arch
c.add_valid("--arch i486 --pxe")  # Convert i*86 -> i686
c.add_valid("--hvm --location %(TREEDIR)s")  # Directory tree URL install
c.add_valid("--hvm --location %(TREEDIR)s --initrd-inject virt-install --extra-args ks=file:/virt-install")  # initrd-inject
c.add_valid("--hvm --location %(TREEDIR)s --extra-args console=ttyS0")  # Directory tree URL install with extra-args
c.add_valid("--hvm --cdrom %(TREEDIR)s")  # Directory tree CDROM install
c.add_valid("--paravirt --location %(TREEDIR)s")  # Paravirt location
c.add_valid("--hvm --cdrom %(ROIMG)s")  # Using ro path as a cd media
c.add_valid("--paravirt --location %(TREEDIR)s --os-variant none")  # Paravirt location with --os-variant none
c.add_valid("--hvm --location %(TREEDIR)s --os-variant fedora12")  # URL install with manual os-variant
c.add_valid("--hvm --pxe --boot menu=on")  # Boot menu
c.add_valid("--hvm --pxe --boot kernel=/tmp/foo1.img,initrd=/tmp/foo2.img,dtb=/tmp/foo2.dtb,kernel_args='ro quiet console=/dev/ttyS0'")  # Kernel params
c.add_valid("--hvm --pxe --boot cdrom,fd,hd,network,menu=off")  # Boot order
c.add_valid("--hvm --boot network,hd,menu=on")  # Boot w/o other install option
c.add_invalid("--hvm --pxe --virt-type bogus")  # Bogus virt-type
c.add_invalid("--hvm --pxe --arch bogus")  # Bogus arch
c.add_invalid("--paravirt --pxe")  # PXE w/ paravirt
c.add_invalid("--import")  # Import with no disks
c.add_invalid("--livecd")  # LiveCD with no media
c.add_invalid("--hvm --pxe --os-variant farrrrrrrge")  # Bogus --os-variant
c.add_invalid("--hvm --pxe --boot menu=foobar")
c.add_invalid("--hvm --cdrom %(EXISTIMG1)s --extra-args console=ttyS0")  # cdrom fail w/ extra-args
c.add_invalid("--hvm --boot kernel=%(TREEDIR)s/pxeboot/vmlinuz,initrd=%(TREEDIR)s/pxeboot/initrd.img --initrd-inject virt-install")  # initrd-inject with manual kernel/initrd




vimag = App("virt-image")
c = vimag.add_category("graphics", "--name test-image --boot 0 %(IMAGE_XML)s")
c.add_valid("--sdl")  # SDL
c.add_valid("--vnc --keymap ja --vncport 5950 --vnclisten 1.2.3.4")  # VNC w/ lots of options


c = vimag.add_category("misc", "")
c.add_valid("--network=?")  # Make sure introspection doesn't blow up
c.add_compare("--name foobar --ram 64 --os-variant winxp --boot 0 %(IMAGE_XML)s", "image-boot0")
c.add_compare("--name foobar --ram 64 --network user,model=e1000 --boot 1 %(IMAGE_XML)s", "image-boot1")
c.add_compare("--name foobar --ram 64 --boot 0 %(IMAGE_NOGFX_XML)s", "image-nogfx")
c.add_valid("--name test --replace %(IMAGE_XML)s")  # Colliding VM name w/ --replace
c.add_invalid("%(IMAGE_XML)s")  # No name specified, and no prompt flag
c.add_invalid("--name test %(IMAGE_XML)s")  # Colliding VM name without --replace


c = vimag.add_category("network", "--name test-image --boot 0 --nographics %(IMAGE_XML)s")
c.add_valid("--network=user")  # user networking
c.add_valid("--network network:default --mac RANDOM")  # VirtualNetwork with a random macaddr
c.add_valid("--network network:default --mac 00:11:22:33:44:55")  # VirtualNetwork with a random macaddr
c.add_valid("--network=user,model=e1000")  # with NIC model
c.add_valid("--network=network:default,model=e1000 --network=user,model=virtio")  # several networks
c.add_invalid("--network=FOO")  # Nonexistent network
c.add_invalid("--network=network:default --mac 1234")  # Invalid mac


c = vimag.add_category("general", "--name test-image %(IMAGE_XML)s")
c.add_valid("")  # All default values
c.add_valid("--print")  # Print default
c.add_valid("--boot 0")  # Manual boot idx 0
c.add_valid("--boot 1")  # Manual boot idx 1
c.add_valid("--name foobar --ram 64 --os-variant winxp")  # Lots of options
c.add_valid("--name foobar --ram 64 --os-variant none")  # OS variant 'none'
c.add_invalid("--boot 10")  # Out of bounds index




vconv = App("virt-convert")
c = vconv.add_category("misc", "")
c.add_compare("%(VC_IMG1)s %(VIRTCONV_OUT)s", "convert-default")  # virt-image to default (virt-image) w/ no convert
c.add_valid("%(VC_IMG1)s -D none %(VIRTCONV_OUT)s")  # virt-image to default (virt-image) w/ no convert
c.add_valid("%(VC_IMG1)s -o virt-image -D none %(VIRTCONV_OUT)s")  # virt-image to virt-image w/ no convert
c.add_valid("%(VC_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s")  # virt-image to vmx w/ no convert
c.add_valid("%(VC_IMG1)s -o vmx -D raw %(VIRTCONV_OUT)s")  # virt-image to vmx w/ raw
c.add_valid("%(VC_IMG1)s -o vmx -D vmdk %(VIRTCONV_OUT)s")  # virt-image to vmx w/ vmdk
c.add_valid("%(VC_IMG1)s -o vmx -D qcow2 %(VIRTCONV_OUT)s")  # virt-image to vmx w/ qcow2
c.add_valid("%(VMX_IMG1)s -o vmx -D none %(VIRTCONV_OUT)s")  # vmx to vmx no convert
c.add_valid("%(VC_IMG2)s -o vmx -D vmdk %(VIRTCONV_OUT)s")  # virt-image with exotic formats specified
c.add_invalid("%(VC_IMG1)s -o virt-image -D foobarfmt %(VIRTCONV_OUT)s")  # virt-image to virt-image with invalid format
c.add_invalid("%(VC_IMG1)s -o ovf %(VIRTCONV_OUT)s")  # virt-image to ovf (has no output formatter)




vclon = App("virt-clone")
c = vclon.add_category("remote", "--connect %(REMOTEURI)s")
c.add_valid("-o test --auto-clone")  # Auto flag, no storage
c.add_valid("--original-xml %(CLONE_STORAGE_XML)s --auto-clone")  # Auto flag w/ managed storage,
c.add_invalid("--original-xml %(CLONE_DISK_XML)s --auto-clone")  # Auto flag w/ storage,


c = vclon.add_category("misc", "")
c.add_compare("--connect %(KVMURI)s -o test-for-clone --auto-clone --clone-running", "clone-auto1")
c.add_compare("-o test-clone-simple --name newvm --auto-clone --clone-running", "clone-auto2")
c.add_valid("-o test --auto-clone")  # Auto flag, no storage
c.add_valid("--original-xml %(CLONE_DISK_XML)s --auto-clone")  # Auto flag w/ storage,
c.add_valid("--original-xml %(CLONE_STORAGE_XML)s --auto-clone")  # Auto flag w/ managed storage,
c.add_valid("-o test-for-clone --auto-clone --clone-running")  # Auto flag, actual VM, skip state check
c.add_valid("-o test-clone-simple -n newvm --preserve-data --file /dev/default-pool/default-vol --clone-running --force")  # Preserve data shouldn't complain about existing volume
c.add_invalid("--auto-clone# Auto flag, actual VM, without state skip ")  # Just the auto flag
c.add_invalid("-o test-for-clone --auto-clone")


c = vclon.add_category("general", "-n clonetest")
c.add_valid("-o test")  # Nodisk guest
c.add_valid("-o test --file %(NEWIMG1)s --file %(NEWIMG2)s")  # Nodisk, but with spurious files passed
c.add_valid("-o test --file %(NEWIMG1)s --file %(NEWIMG2)s --prompt")  # Working scenario w/ prompt shouldn't ask anything
c.add_valid("--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s")  # XML File with 2 disks
c.add_valid("--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s --preserve")  # XML w/ disks, overwriting existing files with --preserve
c.add_valid("--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --file %(NEWIMG3)s --force-copy=hdc")  # XML w/ disks, force copy a readonly target
c.add_valid("--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=fda")  # XML w/ disks, force copy a target with no media
c.add_valid("--original-xml %(CLONE_STORAGE_XML)s --file %(MANAGEDNEW1)s")  # XML w/ managed storage, specify managed path
c.add_valid("--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s --preserve")  # XML w/ managed storage, specify managed path across pools# Libvirt test driver doesn't support cloning across pools# XML w/ non-existent storage, with --preserve
c.add_valid("-o test -n test-many-devices --replace")  # Overwriting existing VM
c.add_invalid("-o test foobar")  # Positional arguments error
c.add_invalid("-o idontexist")  # Non-existent vm name
c.add_invalid("-o idontexist --auto-clone")  # Non-existent vm name with auto flag,
c.add_invalid("-o test -n test")  # Colliding new name
c.add_invalid("--original-xml %(CLONE_DISK_XML)s")  # XML file with several disks, but non specified
c.add_invalid("--original-xml %(CLONE_DISK_XML)s --file virt-install --file %(EXISTIMG1)s")  # XML w/ disks, overwriting existing files with no --preserve
c.add_invalid("--original-xml %(CLONE_DISK_XML)s --file %(NEWIMG1)s --file %(NEWIMG2)s --force-copy=hdc")  # XML w/ disks, force copy but not enough disks passed
c.add_invalid("--original-xml %(CLONE_STORAGE_XML)s --file /tmp/clonevol")  # XML w/ managed storage, specify unmanaged path (should fail)
c.add_invalid("--original-xml %(CLONE_NOEXIST_XML)s --file %(EXISTIMG1)s")  # XML w/ non-existent storage, WITHOUT --preserve
c.add_invalid("--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMG)s --force")  # XML w/ managed storage, specify RO image without preserve
c.add_invalid("--original-xml %(CLONE_DISK_XML)s --file %(ROIMG)s --file %(ROIMGNOEXIST)s --force")  # XML w/ managed storage, specify RO non existent





##########################
# Automated prompt tests #
##########################

# Basic virt-install prompting
p1 = PromptTest("virt-install --connect %(TESTURI)s --prompt --quiet "
               "--noautoconsole")
p1.add("fully virtualized", "yes")
p1.add("What is the name", "foo")
p1.add("How much RAM", "64")
p1.add("use as the disk", "%(NEWIMG1)s")
p1.add("large would you like the disk", ".00001")
p1.add("CD-ROM/ISO or URL", "%(EXISTIMG1)s")
promptlist.append(p1)

# Basic virt-install kvm prompting, existing disk
p2 = PromptTest("virt-install --connect %(KVMURI)s --prompt --quiet "
               "--noautoconsole --name foo --ram 64 --pxe --hvm")
p2.add("use as the disk", "%(EXISTIMG1)s")
p2.add("overwrite the existing path")
p2.add("want to use this disk", "yes")
promptlist.append(p2)

# virt-install with install and --file-size and --hvm specified
p3 = PromptTest("virt-install --connect %(TESTURI)s --prompt --quiet "
               "--noautoconsole --pxe --file-size .00001 --hvm")
p3.add("What is the name", "foo")
p3.add("How much RAM", "64")
p3.add("enter the path to the file", "%(NEWIMG1)s")
promptlist.append(p3)

# Basic virt-image prompting
p4 = PromptTest("virt-image --connect %(TESTURI)s %(IMAGE_XML)s "
               "--prompt --quiet --noautoconsole")
# prompting for virt-image currently disabled
#promptlist.append(p4)

# Basic virt-clone prompting
p5 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--clone-running")
p5.add("original virtual machine", "test-clone-simple")
p5.add("cloned virtual machine", "test-clone-new")
p5.add("use as the cloned disk", "%(MANAGEDNEW1)s")
promptlist.append(p5)

# virt-clone prompt with input XML
p6 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--original-xml %(CLONE_DISK_XML)s --clone-running")
p6.add("cloned virtual machine", "test-clone-new")
p6.add("use as the cloned disk", "%(NEWIMG1)s")
p6.add("use as the cloned disk", "%(NEWIMG2)s")
promptlist.append(p6)

# Basic virt-clone prompting with disk failure handling
p7 = PromptTest("virt-clone --connect %(TESTURI)s --prompt --quiet "
               "--clone-running -o test-clone-simple -n test-clone-new")
p7.add("use as the cloned disk", "/root")
p7.add("'/root' must be a file or a device")
p7.add("use as the cloned disk", "%(MANAGEDNEW1)s")
promptlist.append(p7)



#########################
# Test runner functions #
#########################

newidx = 0
curtest = 0
old_bridge = virtinst.util.default_bridge


def setup():
    """
    Create initial test files/dirs
    """
    os.system("mkdir %s" % ro_dir)

    for i in exist_files:
        os.system("touch %s" % i)

    # Set ro_img to readonly
    os.system("chmod 444 %s" % ro_img)
    os.system("chmod 555 %s" % ro_dir)

    virtinst.util.default_bridge = lambda ignore: None


def cleanup():
    """
    Cleanup temporary files used for testing
    """
    for i in clean_files:
        os.system("chmod 777 %s > /dev/null 2>&1" % i)
        os.system("rm -rf %s > /dev/null 2>&1" % i)

    virtinst.util.default_bridge = old_bridge


class CLITests(unittest.TestCase):
    def setUp(self):
        global curtest
        curtest += 1
        # Only run this for first test
        if curtest == 1:
            setup()

    def tearDown(self):
        # Only run this on the last test
        if curtest == newidx:
            cleanup()


def maketest(cmd):
    def cmdtemplate(self, _cmdobj):
        _cmdobj.run(self)
    return lambda s: cmdtemplate(s, cmd)

_cmdlist = promptlist
_cmdlist += vinst.cmds
_cmdlist += vclon.cmds
_cmdlist += vimag.cmds
_cmdlist += vconv.cmds

for _cmd in _cmdlist:
    newidx += 1
    setattr(CLITests, "testCLI%s%.4d" % (_cmd.app.replace("-", ""), newidx),
            maketest(_cmd))

atexit.register(cleanup)
