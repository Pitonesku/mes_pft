This folder holds the pre-compiled station push agent binary
(station_push_agent.exe) served by GET /api/v2/station-profiles/{id}/download-agent.

Build it once on the MES server with:

    cd mes_pft
    pip install pyinstaller
    .\scripts\build_station_agent.ps1

which outputs station_push_agent.exe here. The download-agent endpoint returns
HTTP 503 until this file exists.
