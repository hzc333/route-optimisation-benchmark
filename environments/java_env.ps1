# Dot-source me: `. .\environments\java_env.ps1`
# Needed only for the Timefold adapter (JDK 21 + Maven). Uses a portable JDK and
# Maven unpacked in <repo>\..\tools (jdk-21*, apache-maven-*) if present;
# otherwise keeps whatever java / mvn is already on PATH. Affects this session only.
$tools = if ($env:ROUTE_OPTI_TOOLS) { $env:ROUTE_OPTI_TOOLS } else { Join-Path (Split-Path (Split-Path $PSScriptRoot)) "tools" }
$jdk = Get-ChildItem $tools -Directory -Filter "jdk-21*" -ErrorAction SilentlyContinue | Select-Object -First 1
$mvn = Get-ChildItem $tools -Directory -Filter "apache-maven-*" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($jdk) { $env:JAVA_HOME = $jdk.FullName; $env:PATH = "$($jdk.FullName)\bin;$env:PATH" }
if ($mvn) { $env:MAVEN_HOME = $mvn.FullName; $env:PATH = "$($mvn.FullName)\bin;$env:PATH" }
if (-not (Get-Command java -ErrorAction SilentlyContinue)) { Write-Warning "java not found: install JDK 21 or set ROUTE_OPTI_TOOLS" }
if (-not (Get-Command mvn -ErrorAction SilentlyContinue)) { Write-Warning "mvn not found: install Maven 3.9 or set ROUTE_OPTI_TOOLS" }
