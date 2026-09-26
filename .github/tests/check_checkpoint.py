import os, pathlib, subprocess, tempfile, sys, time
script=str(pathlib.Path(__file__).resolve().parents[1]/'scripts/github_check_checkpoint.sh')
import shutil
ninja=shutil.which('ninja')
if not ninja: raise SystemExit('Install Ninja before running this regression check')
fixture_directory=tempfile.TemporaryDirectory(prefix='helium-checkpoint-tests-')
root=pathlib.Path(fixture_directory.name)
for case in ['clean','noop_restat','changed_source','changed_sdk','missing_sdk','unsafe_sysroot_plan']:
    src=root/case; out=src/'out/Default';out.mkdir(parents=True);(out/'obj').mkdir();(src/'third_party/depot_tools').mkdir(parents=True)
    (src/'third_party/depot_tools/autoninja.py').write_text('import subprocess,sys\nsys.exit(subprocess.call('+repr([ninja])+'+sys.argv[1:]))\n')
    (src/'noop.py').write_text('pass\n');(src/'sdk.h').write_text('#define VALUE 1\n');(src/'main.c').write_text('#include "sdk.h"\nint value(void) {return VALUE;}\n')
    (out/'build.ninja').write_text('rule noop\n  command = python3 ../../noop.py\n  description = ACTION //build/modules:mac_sysroot(//build/toolchain/mac:clang_arm64)\n  restat = 1\nrule cc\n  command = /usr/bin/clang -MMD -MF $out.d -I ../.. -c ../../main.c -o $out\n  depfile = $out.d\n  deps = gcc\n  description = CXX $out\nbuild ../../sdk.h: noop ../../noop.py\nbuild mac_sysroot: phony ../../sdk.h\nbuild obj/main.o: cc ../../main.c | ../../sdk.h\n')
    subprocess.run([ninja,'-C',str(out),'obj/main.o'],check=True,stdout=subprocess.DEVNULL)
    obj=out/'obj/main.o';before=obj.stat().st_mtime_ns
    if case in ['noop_restat','unsafe_sysroot_plan']:
        os.utime(src/'noop.py',None)
    if case=='changed_source':
        os.utime(src/'main.c',None)
    if case=='changed_sdk':
        (src/'sdk.h').write_text('#define VALUE 2\n');os.utime(src/'sdk.h',None)
    if case=='missing_sdk': (src/'sdk.h').unlink()
    if case=='unsafe_sysroot_plan':
        text=(out/'build.ninja').read_text().replace('build mac_sysroot: phony ../../sdk.h','build mac_sysroot: phony ../../sdk.h other\nrule other\n  command = touch other\n  description = OTHER\nbuild other: other\n');(out/'build.ninja').write_text(text)
    result=subprocess.run(['bash',script,str(src)],capture_output=True,text=True)
    expected=0 if case in ['clean','noop_restat'] else 1
    assert result.returncode==expected,(case,result.returncode,result.stdout,result.stderr)
    assert obj.stat().st_mtime_ns==before,case+' recompiled object'
    if case=='unsafe_sysroot_plan': assert not (out/'other').exists()
    print(case+': PASS (no object compilation)')
fixture_directory.cleanup()
