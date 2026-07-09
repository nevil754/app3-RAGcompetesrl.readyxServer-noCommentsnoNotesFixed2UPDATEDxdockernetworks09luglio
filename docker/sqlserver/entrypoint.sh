set -e

echo "Attendo SQL Server..."
until /opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U SA \
    -P "$SA_PASSWORD" \
    -Q "SELECT 1" > /dev/null 2>&1; do
    sleep 2
done

echo "SQL Server pronto. Eseguo init.sql..."
/opt/mssql-tools18/bin/sqlcmd \
    -S localhost \
    -U SA \
    -P "$SA_PASSWORD" \
    -i /docker-entrypoint-initdb.d/init.sql \
    -b

echo "init.sql completato."

