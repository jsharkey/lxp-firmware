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
]
from ghidra.program.model.symbol import SourceType
for a,n in names:
    addr=af.getAddress(a); f=fm.getFunctionAt(addr)
    if f is None: f=createFunction(addr,n)
    if f is not None: f.setName(n,SourceType.USER_DEFINED)
