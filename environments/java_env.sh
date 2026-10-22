# Source me: `source environments/java_env.sh`
# Needed only for the Timefold adapter (JDK 21 + Maven). Uses a portable JDK and
# Maven unpacked in <repo>/../tools (jdk-21*, apache-maven-*) if present;
# otherwise keeps whatever java / mvn is already on PATH. Affects this shell only.
TOOLS="${ROUTE_OPTI_TOOLS:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/tools}"
JDK="$(ls -d "$TOOLS"/jdk-21* 2>/dev/null | head -1)"
MVN="$(ls -d "$TOOLS"/apache-maven-* 2>/dev/null | head -1)"
if [ -n "$JDK" ]; then export JAVA_HOME="$JDK"; export PATH="$JAVA_HOME/bin:$PATH"; fi
if [ -n "$MVN" ]; then export MAVEN_HOME="$MVN"; export PATH="$MAVEN_HOME/bin:$PATH"; fi
command -v java >/dev/null || echo "java not found: install JDK 21 or set ROUTE_OPTI_TOOLS" >&2
command -v mvn >/dev/null || echo "mvn not found: install Maven 3.9 or set ROUTE_OPTI_TOOLS" >&2
