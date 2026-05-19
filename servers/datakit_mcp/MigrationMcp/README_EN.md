# DataKit MCP Usage Description

DataKit MCP provides the MCP service that uses the DataKit data migration function. DataKit is a visualized web platform system for openGauss databases. For details, visit https://gitcode.com/opengauss/openGauss-workbench.

## Environment Setup

1. Prepare the source and target databases.

   Prepare the source MySQL database service and the target openGauss database service.

2. Set up the DataKit service.

   For details, see the README file in the [openGauss-workbench](https://gitcode.com/opengauss/openGauss-workbench) repository.

3. Prepare the migration executor.

   For details, see the https://gitcode.com/opengauss/openGauss-workbench/blob/master/plugins/data-migration/README.md file.

Note: The data migration function is complex. Before using MCP to migrate data, you are advised to get familiar with the migration service process and operations on the DataKit web page.

## Setting Up the MCP Service

1. Download the code.

   Download the code of the MigrationMcp project to an openEuler Linux environment, and prepare the JDK 21 and Maven 3.8+ environments on the Linux server. Ensure that the environment variables are correctly configured.

2. Open the project.

   Use VSCode to remotely connect to the Linux server specified in step 1 and open the MigrationMcp project.

3. Configure the DataKit service information.

   Modify the `src/main/resources/application.properties` file in the project and configure the DataKit service. Do not modify other configuration items.

   Configure the following information based on the DataKit service set up in **Environment Preparation**:

   ```properties
   # Your DataKit server information
   datakit.url=https://localhost:9494
   datakit.user=admin
   datakit.password=your_password
   ```

   Then, obtain the `publicKey` content from [openGauss-workbench/blob/master/plugins](https://gitcode.com/opengauss/openGauss-workbench/blob/master/plugins/compatibility-assessment/web-ui/src/utils/jsencrypt.ts) and configure the `EncryptUtils.PUBLIC_KEY` field in the `src/main/java/org/opengauss/migrationmcp/utils/EncryptUtils.java` file of the project.

4. Package projects.

   In the project directory, run the `mvn clean package -DskipTests` command to package the project. After the packaging is successful, you can see the `target/MigrationMcp-0.0.1-SNAPSHOT.jar` file in the project directory.

5. Configure the MCP service.

   Download the `Roo Code` plugin in VSCode and configure the DeepSeek-V3 API. Modify the `.roo/mcp.json` file in the project directory. The file content is as follows:

   ```json
   {
     "mcpServers": {
       "migration-mcp": {
         "command": "java",
         "args": [
           "-jar",
           "./target/MigrationMcp-0.0.1-SNAPSHOT.jar"
         ],
         "disabled": false,
         "timeout": 3600,
         "alwaysAllow": [
           "Source database cluster list"
           "Creating data migration tasks"
           "List of databases contained in the destination database"
           "Data migration task list"
           "List of databases contained in the source database"
           "List of destination databases"
           "Starting data migration tasks"
           "Source database list"
         ]
       }
     }
   }
   ```
   
   Note: If the error message `MCP error -32000: Connection closed` is displayed when you run the **java** command, change the command to the absolute path of java and restart the MCP service.

6. Check the MCP service.

   After the preceding configuration is complete, you can see that `migration-mcp` is correctly loaded and its status is normal on the **MCP Service Management** tab page of the `Roo Code` plugin. On the **Tools** tab page, you can view the functions supported by the MCP service.

## MCP Service Usage Guide

You can use commands similar to the following to access the MCP service and start the data migration task:

1. How do I create and start a data migration task?
2. Can you list all source and destination databases?
3. Can you help me query the databases in 127.0.0.1:3306?
4. Can you help me create a migration task using source_db in 127.0.0.1:3306 and target_db in 127.0.0.1:5432?
5. Can you help me start the migration task created in the previous step?

## Precautions

1. This project is only a demo for DataKit data migration to adapt to the MCP service. Currently, only the functions provided on the **Tools** tab page are supported. For functions such as migration progress check, you need to use the DataKit web page.
2. Before starting the MCP service, you need to start DataKit. Otherwise, the MCP service fails to be started.
3. Due to limited functions, you need to add the source and target data sources and prepare the migration executor on the original DataKit web page.
4. After the packaging is complete, do not change the DataKit service port or user password. Otherwise, the MCP service may fail to connect to the DataKit service.
