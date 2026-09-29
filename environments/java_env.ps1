# Dot-source me: `. .\environments\java_env.ps1`
# Portable JDK 21 (Temurin) + Maven under D:\route_opti\tools; affects this session only.
$tools = Join-Path (Split-Path (Split-Path $PSScriptRoot)) "tools"
$env:JAVA_HOME = (Get-ChildItem $tools -Directory -Filter "jdk-21*" | Select-Object -First 1).FullName
$env:MAVEN_HOME = (Get-ChildItem $tools -Directory -Filter "apache-maven-*" | Select-Object -First 1).FullName
$env:PATH = "$env:JAVA_HOME\bin;$env:MAVEN_HOME\bin;$env:PATH"
