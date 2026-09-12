if {[catch {package require ::quartus::insystem_source_probe} err]} {
    if {![llength [info commands start_insystem_source_probe]]} {
        puts stderr "FATAL: no In-System Sources and Probes API available: $err"
        exit 1
    }
}

set instance_index 0
set hardware_filter ""
set port ""

for {set i 0} {$i < [llength $argv]} {incr i} {
    switch -- [lindex $argv $i] {
        "-instance" { incr i; set instance_index [lindex $argv $i] }
        "-hardware" { incr i; set hardware_filter [lindex $argv $i] }
        "-port"     { incr i; set port [lindex $argv $i] }
        default {
            puts stderr "FATAL: unknown argument [lindex $argv $i]"
            exit 1
        }
    }
}

if {$port eq ""} {
    puts stderr "FATAL: -port is required; start this through scripts/board/jtag_keys.py"
    exit 1
}

if {[catch {set sock [socket 127.0.0.1 $port]} err]} {
    puts stderr "FATAL: cannot reach the client on port $port: $err"
    exit 1
}
fconfigure $sock -buffering line -translation lf

proc reply {text} {
    global sock
    puts $sock "@@$text"
}

set key_width 4

proc to_binary {value width} {
    set bits ""
    for {set i [expr {$width - 1}]} {$i >= 0} {incr i -1} {
        append bits [expr {($value >> $i) & 1}]
    }
    return $bits
}

proc from_binary {bits} {
    set value 0
    foreach bit [split $bits ""] {
        if {$bit ne "0" && $bit ne "1"} { error "not a binary string: '$bits'" }
        set value [expr {($value << 1) | $bit}]
    }
    return $value
}

proc select_hardware {filter} {
    set names [get_hardware_names]
    if {[llength $names] == 0} {
        error "no programming hardware found (is the USB-Blaster connected?)"
    }
    if {$filter ne ""} {
        foreach name $names {
            if {[string match -nocase "*$filter*" $name]} { return $name }
        }
        error "no programming hardware matching '$filter' in: $names"
    }
    return [lindex $names 0]
}

proc select_device {hardware} {
    set names [get_device_names -hardware_name $hardware]
    if {[llength $names] == 0} {
        error "no devices on $hardware"
    }
    foreach name $names {
        if {[string match -nocase "*5CSEMA*" $name]} { return $name }
    }
    foreach name $names {
        if {![string match -nocase "*SOCVHPS*" $name]} { return $name }
    }
    return [lindex $names 0]
}

if {[catch {
    set hardware [select_hardware $hardware_filter]
    set device [select_device $hardware]
    start_insystem_source_probe -device_name $device -hardware_name $hardware
} err]} {
    reply "FATAL $err"
    catch { close $sock }
    exit 1
}

reply "READY $device"

while {[gets $sock line] >= 0} {
    set line [string trim $line]
    if {$line eq ""} { continue }
    set command [string toupper [lindex $line 0]]

    switch -- $command {
        "SET" {
            set value [lindex $line 1]
            if {![string is integer -strict $value]} {
                reply "ERR SET needs a decimal mask, got '$value'"
                continue
            }
            if {[catch {
                write_source_data -instance_index $instance_index \
                    -value [to_binary $value $key_width]
            } err]} {
                reply "ERR $err"
            } else {
                reply "OK"
            }
        }
        "GET" {
            if {[catch {
                set value [from_binary \
                    [read_source_data -instance_index $instance_index]]
            } err]} {
                reply "ERR $err"
            } else {
                reply "VALUE $value"
            }
        }
        "PING" { reply "OK" }
        "QUIT" {
            catch {
                write_source_data -instance_index $instance_index \
                    -value [to_binary 0 $key_width]
            }
            reply "BYE"
            break
        }
        default { reply "ERR unknown command '$command'" }
    }
}

catch { end_insystem_source_probe }
catch { close $sock }
exit 0
