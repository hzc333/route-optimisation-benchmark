# Source me: `source environments/java_env.sh`
# Portable JDK 21 (Temurin) + Maven under D:\route_opti\tools; affects this shell only.
TOOLS="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/tools"
export JAVA_HOME="$(ls -d "$TOOLS"/jdk-21* | head -1)"
export MAVEN_HOME="$(ls -d "$TOOLS"/apache-maven-* | head -1)"
export PATH="$JAVA_HOME/bin:$MAVEN_HOME/bin:$PATH"
