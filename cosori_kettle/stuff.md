Protocol appears to be:
- envelope: 6 bytes:
    - 0xA5 // magic
    - 0x22 (message) | 0x21 (ack)
    - 0x00-0xFF - sequence (ack matches command seq)
    - 0x00-0xFF - length low byte
    - 0x00-0xFF - length high byte
    - 0x00-0xFF - checksum
- command: 4 bytes:
    - 0x00|0x01 - protocol version?
    - 0x00-0xFF - command ID
    - 0x40|0xA3 (thought it was from device vs from control, but not consistent?)
    - 0x00 - padding?
- ... body

---------------------------------------------------

v1 commands:
- start heating:  01F0 A300 yyyy bb zzzz
- delay start:    01F1 A300 xxxx yyyy bb zzzz
- set "hold temp" 01F2 A300 00bb zzzz
  xxxx: delay in seconds in big-endian (10_0E == 3600s == 60 minutes)
  yyyy: mode (0300 for coffee, 0400 for boil, 0500 for "mytemp", etc.)
  bb: enable hold (01 on, 00 off)
  zzzz: hold time in seconds in big-endian (34_08 == 2100s == 35 mins)
- set mytemp temp: 01F3 A300 {temp}
- stop: 01F4 A300
- set mytemp baby-formula mode: 01F5_A300_{0 or 1}
- sent from device when it finished..: 01F7 A300 xx
  xx: 20 = done (might hold), 21 = hold done
- hello: 0181 D100 {bytes}
  bytes: 32 bytes which is 16 byte key encoded as ascii hex. appears to be tied to the controller device/app or the account
  - ack will have payload '00' on success
- register: 0180 D100 {bytes}
  - ack will have payload '00' on success
  - device must be in pairing mode

----------------------------------------------------------


- start 205, no hold:  A522 xxxx xxxx 01F0 A300 0300 0000 00  
- start 212, no hold:  A522 xxxx xxxx 01F0 A300 0400 0000 00  
- start 205, hold 20m: A522 xxxx xxxx 01F0 A300 0300 01B0 04
- start 205, hold 35m: A522 xxxx xxxx 01F0 A300 0300 0134 08
- start "myt", no hld: A522 xxxx xxxx 01F0 A300 0500 0000 00

- stop: A522 xxxx xxxx 01F4 A300


- set mytemp to 179:
  - Set Temp:
    - Write Request - Handle:0x000E - Value:             A522 1C05 00CD 01F3 A300 B3
    - Handle Value Notification - Handle:0x0010 - Value: A512 1C04 0091 01F3 A300
  - Set Baby formula mode:
    - Write Request - Handle:0x000E - Value:             A522 1D05 007D 01F5 A300 00
    - Handle Value Notification - Handle:0x0010 - Value: A512 1D04 008E 01F5 A300
  - Handle Value Notification - Handle:0x0010 - Value:   A522 B50C 00B3 0141 4000 0000 B38F 0000 0000


- set mytemp to 175 baby-formula mode
  - Write Request - Handle:0x000E - Value: A522 2405 00C9 01F3 A300 AF
  - Write Request - Handle:0x000E - Value: A522 2505 0074 01F5 A300 01
  -                                  State A522 C20C 00B0 0141 4000 0000 AF89 0000 0000
- set mytemp to 175 no baby-formula mode, status:
  A522 0D0C 0083 | 0141 4000 | 0000 AF6B 0000 0000 

- start boil in 1h 3min:
  -         A522 290B 0099 01F1 A300 C40E 0400 0000 00
  - status  A522 D00C 007B 0141 4000 0504 D482 0000 0000
  - cancel: A522 2A04 0072 01F4 A300
  

temp 205, hold 35m, delay 1h
Value: A522 510B 00E9 01F1 A300 100E 0300 0134 08

temp boil, hold 35m, delay 1h
Value: A522 540B 00E5 01F1 A300 100E 0400 0134 08

temp boil, hold 20m, delay 1h
Value: A522 580B 0069 01F1 A300 100E 0400 01B0 04

temp boil, no hold, delay 1h
Value: A522 5B0B 001B 01F1 A300 100E 0400 0000 00

temp boil, no hold, delay 1h 1m
Value: A522 5E0B 00DC 01F1 A300 4C0E 0400 0000 00

temp boil, no hold, delay 10m
Value: A522 610B 00D9 01F1 A300 5802 0400 0000 00


from device on removal from base:
A512 401D 0093 | 0140 4000 0000 AF69 AF00 0000 0000 0100 00C4 0E00 0000 0000 3408 0000 01


back on base:
A522 1F0C 0073 0141 4000 0000 AF69 0000…  
A522 200C 008A 0141 4000 0000 AF51 0000…  
A522 210C 0088 0141 4000 0000 AF51 0001…  
A522 4104 0072 0140 4000  

Done: A522 9805 00E0 | 01F7 A300 20

-----------------

maybe error state??

A512 631D 0071 0140 4000 0304 D4D4 AF01 B004 B004 0000 0058 0200 0000 0000 (B004) 0000 01
A512 641D 0070 0140 4000 0304 D4D4 AF01 B004 B004 0000 0058 0200 0000 0000 (B004) 0000 01


-------------------------


start: Write Request - Handle:0x000E - Value:
A522 4809 0050 01F0 A300 0300 0000 00

turn on hold: Write Request - Handle:0x000E - Value:
A522 4908 0014 01F2 A300 0001 3408

A522 AF0C 009E 0141 4000 0103 CD8B 0100 0000 
A522 C10C 006C 0141 4000 0103 CDAB 0100 0000 
A522 D10C 003C 0141 4000 0103 CDCB 0100 0000 

A522 D205 00A6 01F7 A300 20

A522 D30C 0036 0141 4000 0303 CDCD 0100 0000 

-- send A522 4A04 0069 0140 4000
        A512 4A1D 0089 0140 4000 0303 CDCD AF01 3408 3408 0000 00C4 0E00 0000 0000 3408 0000 01

-- send A522 4B04 0068 0140 4000
        A512 4B1D 0088 0140 4000 0303 CDCD AF01 3408 3408 0000 00C4 0E00 0000 0000 3408 0000 01

A522 D40C 002E 0141 4000 0303 CDD4 0100 0000 

holding:
A522 D70C 002E 0141 4000 0303 CDD1 0100 0000 

holding, ~5 min remain: A512 7F1D 004C 0140 4000 0301 B4B3 AF01 2C01 | 0E01 | 0000 0058 0200 0000 0000 2C01 0000 01
holding, ~3 min remain: A512 831D 00B6 0140 4000 0301 B4B5 AF01 2C01 | 9F00 | 0000 0058 0200 0000 0000 2C01 0000 01
holding, ~1 min remain: A512 771D 001B 0140 4000 0301 B4B5 AF01 2C01 | 4600 | 0000 0058 0200 0000 0000 2C01 0000 01
                   hold seconds remaining big-endian                   ^^^^

status with mybrew at 104, no baby: A512 871D 0016 0140 4000 0000 68B5 6800 0000 0000 0000 0058 0200 0000 0000 2C01 0000 01
status with mybrew at 110, no baby: A512 8F1D 0006 0140 4000 0000 6EB1 6E00 0000 0000 0000 0058 0200 0000 0000 2C01 0000 01
status with mybrew at 149, no baby: A512 931D 00B8 0140 4000 0000 xxAD 9500 0000 0000 0000 0058 0200 0000 0000 2C01 0000 01
status with mybrew at 104, baby:    A512 8B1D 0014 0140 4000 0000 68B2 68)0 0000 0000 0000 0058 0200 0000 0000 2C01 0100 01

hold timer end:
Handle Value Notification - Handle:0x0010 - Value: A522 E105 0096 01F7 A300 21


# Me starting and stopping with various temperature settings 180, stop, 195, stop, 205, 212, 140
A522 0309 0097 01F0 A300 0100 0000 00  
A512 0304 00AD 01F0 A300  

A522 1D0C 0068 0141 4000 0101 B46F 0000…  

A522 0404 0098 01F4 A300  
A512 0404 00A8 01F4 A300  

A522 1E0C 0069 0141 4000 0000 B46F 0000…  

A522 0509 0094 01F0 A300 0200 0000 00  
A512 0504 00AB 01F0 A300  

A522 1F0C 0056 0141 4000 0102 C36F 0000…  

A522 0604 0096 01F4 A300  
A512 0604 00A6 01F4 A300  

A522 200C 0058 0141 4000 0000 C36F 0000…  

A522 0709 0091 01F0 A300 0300 0000 00  
A512 0704 00A9 01F0 A300  

A522 210C 0049 0141 4000 0103 CD6F 0000…  

A522 0809 008F 01F0 A300 0400 0000 00  
A512 0804 00A8 01F0 A300  

A522 220C 0040 0141 4000 0104 D46F 0000…  

A522 0909 008D 01F0 A300 0500 0000 00  
A512 0904 00A7 01F0 A300  

A522 230C 0086 0141 4000 0105 8C6F 0000…  

A522 0A04 0092 01F4 A300  
A512 0A04 00A2 01F4 A300  

A522 240C 008B 0141 4000 0000 8C6F 0000…  

A522 250C 0089 0141 4000 0000 8C70 0000…  

A522 260C 0087 0141 4000 0000 8C71 0000…  

A522 270C 0085 0141 4000 0000 8C72 0000…  
 