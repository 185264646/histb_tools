# 海思HiSTB系列SoC BootROM串口下载流程

# 数据结构
```c
enum hisi_packet_type {
	hisi_pkt_type_frame = 0xBD; // TSerialComm::SendTypeFrame()
	hisi_pkt_file_head = 0xFE; // TSerialComm::SendHeadFrame()
	hisi_pkt_file_data = 0xDA; // TSerialComm::SendDataFrame()
	hisi_pkt_file_tail = 0xED; // TSerialComm::SendTailFrame()
	hisi_pkt_board_frame = 0xCE; // TSerialComm::SendBoardFrame()
};

// 海思串口发送包，明显修改自 xmodem
struct hisi_packet {
	u8 type; // 包类型,取值为enum hisi_packet_type
	u16 no; // 序号
	u16 no2; // 序号取反
	u8 payload[]; // 大小根据type而定的负载
	u16 checksum; // CRC-16
} __attribute__((packed));

enum checksum_state {
	checksum_okay = 0xAA;
	checksum_bad = 0x55;
};

// 板子返回的包，跟发送包有些差异
// 还有一种形式：如果不返回数据就只返回checksum_state
struct hisi_packet_ret {
	u8 type; // 包类型，跟上面相同，>0x80
	u8 payload[]; // 返回值，大小看type
	u16 checksum;
	u8 checksum_state; // enum checksum_state
};
```

# 顺序
## SendTypeFrame()
```c
// 作为hisi_packet_ret的payload
struct hisi_chip_info {
	bool CA: 1;
	bool TEE: 1;
	bool multiform: 1;
	u8 _pad1[2]; // padding
	uint32_t boot_version; // big-endian
	uint32_t system_id; // big-endian
} __attribute__((packed));
	
// sizeof(struct hisi_chip_info) == 11
```
获取芯片信息，根据逆向结果，至少包含`boot version, CA, TEE, Multi Form, system id`五项，具体含义未知<br>
看起来这五项都会影响整个串口下载流程和包的结构

## SendHeadData()
按文件传输Head Area, 偏移似乎总是0
## SendAuxcode()
按文件传输Auxcode，偏移算法未知，建议从image中直接读取
## NonCAReSendParamArea()
```c
struct hisi_board_frame_ret {
	u8 _pad1[3];
	u32 unknown_data;
} __pack__(1);
```
传输Param Area。分成两步：SendBoardFrame()和SendParamArea()<br>
ParamArea用文件形式传，偏移量算法未知，似乎与SendBoardFrame的返回值有关，建议直接从image中读取
## SendBoot()
按文件传完整个Boot，偏移量为0
## 文件传输 SendFile()
需要传递两个参数，偏移量offset和长度length，取值根据情况而定<br>
分为三步，每个包发完后序号要递增，到256后自动wrap回0
### SendHeadFrame()
### SendDataFrame()
文件分为1KB的块，不足1K的部分要补足到1K
### SendTailFrame()

