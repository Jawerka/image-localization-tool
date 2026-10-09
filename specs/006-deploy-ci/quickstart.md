# Quickstart: 006 Deploy + CI

```powershell
# Windows apps mirror (build optional)
.\scripts\deploy-windows.ps1
.\scripts\deploy-windows.ps1 -Build -SkipInno
.\scripts\deploy-windows.ps1 -Dest "D:\Documents\apps\ImageLocalizationTool"

# LAN / CT113
.\scripts\deploy-lan.ps1
.\scripts\deploy-lan.ps1 -Hosts @("192.168.88.41","192.168.88.168") -DryRun

# Same filter as CI
pytest tests/unit -m "not slow and not ui and not requires_llm and not requires_argos" -q
```
