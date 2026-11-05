# Ghidra: apply recovered names. Run in Script Manager after import at base 0x08000000.
fm=currentProgram.getFunctionManager()
af=currentProgram.getAddressFactory().getDefaultAddressSpace()
names=[
  (0x080018a4,'SysTick_Handler'),
  (0x0800231c,'SystemInit'),
  (0x080023ee,'SetSysClock'),
  (0x08002888,'NMI_Handler'),
  (0x0800288a,'HardFault_Handler'),
  (0x0800288c,'MemManage_Handler'),
  (0x0800288e,'BusFault_Handler'),
  (0x08002890,'UsageFault_Handler'),
  (0x08002892,'SVCall_Handler'),
  (0x08002894,'DebugMon_Handler'),
  (0x08002896,'PendSV_Handler'),
  (0x08002898,'USART3_IRQHandler'),
  (0x080028a0,'PVD_IRQHandler'),
  (0x08002938,'__scatterload'),
  (0x08002980,'Reset_Handler'),
  (0x08002990,'__main'),
  (0x080029a8,'Default_Handler'),
  (0x080076ce,'fn_ceaa'),
  (0x0800b884,'fn_download'),
  (0x0800c9a0,'fn_Hybrid_Setting'),
  (0x0800caa6,'fn_Parallel_Setting'),
  (0x0800cf88,'fn_Smart_Load'),
  (0x0800d0c8,'fn_AC_Couple'),
  (0x0800e3f0,'fn_NO_Fault'),
  (0x0800e51c,'fn_NO_Alarm'),
  (0x0801b6b2,'fn_ceaa'),
  (0x0801f1a0,'fn_FreedWON'),
  (0x08020330,'fn_eTower'),
  (0x08032000,'fn_ceaa'),
  (0x0803cbf8,'fn_Meter'),
]
from ghidra.program.model.symbol import SourceType
for a,n in names:
    addr=af.getAddress(a); f=fm.getFunctionAt(addr)
    if f is None: f=createFunction(addr,n)
    if f is not None: f.setName(n,SourceType.USER_DEFINED)
