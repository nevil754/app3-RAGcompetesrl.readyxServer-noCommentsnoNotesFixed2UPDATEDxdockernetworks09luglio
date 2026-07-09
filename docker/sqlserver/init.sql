USE master;
GO

IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = 'RAGChat')
BEGIN
    CREATE DATABASE RAGChat
    COLLATE Latin1_General_100_CI_AS_SC_UTF8;
END
GO

USE RAGChat;
GO

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'shared')
    EXEC('CREATE SCHEMA shared');
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'tenants'
)
CREATE TABLE shared.tenants (
    id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
    slug            NVARCHAR(100)       NOT NULL,
    display_name    NVARCHAR(255)       NOT NULL,
    plan            NVARCHAR(50)        NOT NULL DEFAULT 'starter',
    is_active       BIT                 NOT NULL DEFAULT 1,
    max_docs        INT                 NOT NULL DEFAULT 500,
    max_users       INT                 NOT NULL DEFAULT 10,
    max_tokens_day  BIGINT              NOT NULL DEFAULT 100000,
    settings        NVARCHAR(MAX)       NULL,
    created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_tenants PRIMARY KEY (id),
    CONSTRAINT UQ_tenants_slug UNIQUE (slug),
    CONSTRAINT CK_tenants_plan CHECK (plan IN ('starter','pro','enterprise'))
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'audit_log'
)
CREATE TABLE shared.audit_log (
    id          BIGINT IDENTITY(1,1)    NOT NULL,
    tenant_id   UNIQUEIDENTIFIER        NOT NULL,
    user_id     UNIQUEIDENTIFIER        NULL,
    action      NVARCHAR(100)           NOT NULL,
    resource    NVARCHAR(500)           NULL,
    ip_address  NVARCHAR(45)            NULL,
    user_agent  NVARCHAR(500)           NULL,
    metadata    NVARCHAR(MAX)           NULL,
    created_at  DATETIME2(3)               NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_audit_log PRIMARY KEY (id),
    CONSTRAINT FK_audit_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

CREATE INDEX IX_audit_tenant_date ON shared.audit_log (tenant_id, created_at DESC);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'usage_stats'
)
CREATE TABLE shared.usage_stats (
    id              BIGINT IDENTITY(1,1) NOT NULL,
    tenant_id       UNIQUEIDENTIFIER     NOT NULL,
    stat_date       DATE                 NOT NULL,
    tokens_in       BIGINT               NOT NULL DEFAULT 0,
    tokens_out      BIGINT               NOT NULL DEFAULT 0,
    queries_count   INT                  NOT NULL DEFAULT 0,
    docs_ingested   INT                  NOT NULL DEFAULT 0,
    CONSTRAINT PK_usage PRIMARY KEY (id),
    CONSTRAINT UQ_usage_tenant_date UNIQUE (tenant_id, stat_date),
    CONSTRAINT FK_usage_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id = s.schema_id
    WHERE s.name = 'shared' AND t.name = 'api_keys'
)
CREATE TABLE shared.api_keys (
    id          UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
    tenant_id   UNIQUEIDENTIFIER    NOT NULL,
    key_hash    NVARCHAR(64)        NOT NULL,
    [name]        NVARCHAR(255)       NOT NULL,
    scopes      NVARCHAR(500)       NOT NULL DEFAULT 'read,write',
    is_active   BIT                 NOT NULL DEFAULT 1,
    last_used   DATETIME2(3)           NULL,
    expires_at  DATETIME2(3)           NULL,
    created_at  DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_api_keys PRIMARY KEY (id),
    CONSTRAINT UQ_api_keys_hash UNIQUE (key_hash),
    CONSTRAINT FK_api_keys_tenants FOREIGN KEY (tenant_id) REFERENCES shared.tenants(id)
);
GO

CREATE OR ALTER PROCEDURE shared.sp_provision_tenant
    @slug           NVARCHAR(100),
    @display_name   NVARCHAR(255),
    @plan           NVARCHAR(50) = 'starter'
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @schema_name NVARCHAR(200) = 'tenant_' + REPLACE(@slug, '-', '_');
    DECLARE @sql NVARCHAR(MAX);

    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = @schema_name)
    BEGIN
        SET @sql = 'CREATE SCHEMA [' + @schema_name + ']';
        EXEC sp_executesql @sql;
    END

    IF NOT EXISTS (SELECT 1 FROM shared.tenants WHERE slug = @slug)
    BEGIN
        INSERT INTO shared.tenants (slug, display_name, plan)
        VALUES (@slug, @display_name, @plan);
    END

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''users''
    )
    CREATE TABLE [' + @schema_name + '].users (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        email           NVARCHAR(255)       NOT NULL,
        full_name       NVARCHAR(255)       NULL,
        role            NVARCHAR(50)        NOT NULL DEFAULT ''user'',
        password_hash   NVARCHAR(255)       NULL,
        is_active       BIT                 NOT NULL DEFAULT 1,
        last_login      DATETIME2(3)           NULL,
        settings        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_users] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_users_email] UNIQUE (email),
        CONSTRAINT [CK_' + @schema_name + '_users_role] CHECK (role IN (''admin'',''user'',''viewer''))
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''collections''
    )
    CREATE TABLE [' + @schema_name + '].collections (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        name            NVARCHAR(255)       NOT NULL,
        description     NVARCHAR(1000)      NULL,
        qdrant_name     NVARCHAR(300)       NOT NULL,
        is_active       BIT                 NOT NULL DEFAULT 1,
        metadata        NVARCHAR(MAX)       NULL,
        created_by      UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),  
        CONSTRAINT [PK_' + @schema_name + '_collections] PRIMARY KEY (id),
        CONSTRAINT [UQ_' + @schema_name + '_qdrant_name] UNIQUE (qdrant_name)
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''documents''
    )
    CREATE TABLE [' + @schema_name + '].documents (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        collection_id   UNIQUEIDENTIFIER    NULL,
        filename        NVARCHAR(500)       NOT NULL,
        original_name   NVARCHAR(500)       NOT NULL,
        file_hash       NVARCHAR(64)        NOT NULL,
        file_size       BIGINT              NOT NULL DEFAULT 0,
        mime_type       NVARCHAR(100)       NULL,
        storage_path    NVARCHAR(1000)      NULL,
        status          NVARCHAR(50)        NOT NULL DEFAULT ''pending'',
        chunk_count     INT                 NULL,
        page_count      INT                 NULL,
        language        NVARCHAR(10)        NULL DEFAULT ''it'',
        metadata        NVARCHAR(MAX)       NULL,
        uploaded_by     UNIQUEIDENTIFIER    NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_documents] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_doc_status] CHECK (
            status IN (''pending'',''processing'',''ready'',''error'',''deleted'')
        )
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_doc_hash'')
        CREATE INDEX [IX_' + @schema_name + '_doc_hash]
        ON [' + @schema_name + '].documents (file_hash)';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''ingestion_jobs''
    )
    CREATE TABLE [' + @schema_name + '].ingestion_jobs (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        document_id     UNIQUEIDENTIFIER    NOT NULL,
        celery_task_id  NVARCHAR(255)       NULL,
        status          NVARCHAR(50)        NOT NULL DEFAULT ''queued'',
        progress_pct    TINYINT             NOT NULL DEFAULT 0,
        error_msg       NVARCHAR(MAX)       NULL,
        retry_count     TINYINT             NOT NULL DEFAULT 0,
        started_at      DATETIME2(3)           NULL,
        finished_at     DATETIME2(3)           NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_jobs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_job_status] CHECK (
            status IN (''queued'',''running'',''done'',''failed'',''cancelled'')
        )
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''conversations''
    )
    CREATE TABLE [' + @schema_name + '].conversations (
        id              UNIQUEIDENTIFIER    NOT NULL DEFAULT NEWSEQUENTIALID(),
        user_id         UNIQUEIDENTIFIER    NOT NULL,
        collection_id   UNIQUEIDENTIFIER    NULL,
        title           NVARCHAR(500)       NULL,
        mode            NVARCHAR(50)        NOT NULL DEFAULT ''rag'',
        is_archived     BIT                 NOT NULL DEFAULT 0,
        metadata        NVARCHAR(MAX)       NULL,
        created_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2(3)           NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_convs] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''messages''
    )
    CREATE TABLE [' + @schema_name + '].messages (
        id                  BIGINT IDENTITY(1,1)    NOT NULL,
        conversation_id     UNIQUEIDENTIFIER        NOT NULL,
        role                NVARCHAR(20)            NOT NULL,
        content             NVARCHAR(MAX)           NOT NULL,
        sources             NVARCHAR(MAX)           NULL,
        tokens_in           INT                     NULL,
        tokens_out          INT                     NULL,
        latency_ms          INT                     NULL,
        model_used          NVARCHAR(100)           NULL,
        hallucination_score FLOAT                   NULL,
        created_at          DATETIME2(3)               NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_msgs] PRIMARY KEY (id),
        CONSTRAINT [CK_' + @schema_name + '_msg_role] CHECK (role IN (''user'',''assistant'',''system''))
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_msgs_conv'')
        CREATE INDEX [IX_' + @schema_name + '_msgs_conv]
        ON [' + @schema_name + '].messages (conversation_id, created_at)';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''message_feedback''
    )
    CREATE TABLE [' + @schema_name + '].message_feedback (
        id          BIGINT IDENTITY(1,1) NOT NULL,
        message_id  BIGINT               NOT NULL,
        user_id     UNIQUEIDENTIFIER     NOT NULL,
        rating      TINYINT              NOT NULL,
        comment     NVARCHAR(1000)       NULL,
        created_at  DATETIME2(3)            NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_feedback] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''conversation_summaries''
    )
    CREATE TABLE [' + @schema_name + '].conversation_summaries (
        id              BIGINT IDENTITY(1,1)    NOT NULL,
        conversation_id UNIQUEIDENTIFIER        NOT NULL,
        user_id         UNIQUEIDENTIFIER        NOT NULL,
        summary_text    NVARCHAR(MAX)           NOT NULL,
        turn_count      INT                     NOT NULL DEFAULT 0,
        from_turn       INT                     NOT NULL DEFAULT 0,
        to_turn         INT                     NOT NULL DEFAULT 0,
        created_at      DATETIME2(3)            NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_conv_summ] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (
        SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ''' + @schema_name + ''' AND t.name = ''user_facts''
    )
    CREATE TABLE [' + @schema_name + '].user_facts (
        id              BIGINT IDENTITY(1,1)    NOT NULL,
        user_id         UNIQUEIDENTIFIER        NOT NULL,
        fact_type       NVARCHAR(50)            NOT NULL DEFAULT ''generic'',
        fact_key        NVARCHAR(255)           NOT NULL,
        fact_value      NVARCHAR(MAX)           NOT NULL,
        confidence      FLOAT                   NOT NULL DEFAULT 1.0,
        is_active       BIT                     NOT NULL DEFAULT 1,
        source_conv_id  UNIQUEIDENTIFIER        NULL,
        created_at      DATETIME2(3)            NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIME2(3)            NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [PK_' + @schema_name + '_user_facts] PRIMARY KEY (id)
    )';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = ''IX_' + @schema_name + '_user_facts_user'')
        CREATE INDEX [IX_' + @schema_name + '_user_facts_user]
        ON [' + @schema_name + '].user_facts (user_id, is_active, confidence DESC)';
    EXEC sp_executesql @sql;

    SET @sql = '
    IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = ''usr_' + @schema_name + ''')
        CREATE USER [usr_' + @schema_name + '] WITHOUT LOGIN
        WITH DEFAULT_SCHEMA = [' + @schema_name + ']';
    EXEC sp_executesql @sql;

    SET @sql = 'GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::[' + @schema_name + '] TO [usr_' + @schema_name + ']';
    EXEC sp_executesql @sql;

    PRINT 'Tenant provisioned: ' + @schema_name;
END
GO

EXEC shared.sp_provision_tenant
    @slug         = 'demo-corp',
    @display_name = 'Demo Corporation',
    @plan         = 'pro';
GO

PRINT 'init.sql completato.';
GO

