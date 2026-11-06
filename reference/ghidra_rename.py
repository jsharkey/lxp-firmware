# Ghidra: apply recovered names. Run in Script Manager after import at base 0x08000000.
fm=currentProgram.getFunctionManager()
af=currentProgram.getAddressFactory().getDefaultAddressSpace()
names=[
  (0x08007458,'fn_pGceaa'),
  (0x0800ba10,'fn_download'),
  (0x0800cbfe,'fn_Hybrid_Setting'),
  (0x0800cd08,'fn_Parallel_Setting'),
  (0x0800d366,'fn_Smart_Load'),
  (0x0800d494,'fn_AC_Couple'),
  (0x0800e834,'fn_NO_Fault'),
  (0x0800e958,'fn_NO_Alarm'),
  (0x0801a93a,'fn_pGceaa'),
  (0x0801d48c,'fn_pGceaa'),
  (0x08022924,'fn_eTower'),
  (0x080359dc,'fn_FreedWON'),
]
from ghidra.program.model.symbol import SourceType
for a,n in names:
    addr=af.getAddress(a); f=fm.getFunctionAt(addr)
    if f is None: f=createFunction(addr,n)
    if f is not None: f.setName(n,SourceType.USER_DEFINED)
