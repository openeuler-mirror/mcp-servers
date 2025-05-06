# DataKit Mcp使用说明

DataKit Mcp提供了使用DataKit数据迁移功能的MCP服务。DataKit为openGauss数据库的可视化Web平台系统，了解详情：https://gitcode.com/opengauss/openGauss-workbench

## 环境准备

1. 准备源端和目标端数据库

   准备源端MySQL数据库服务，准备目标端openGauss数据库服务

2. 搭建DataKIt服务

   参考https://gitcode.com/opengauss/openGauss-workbench仓库中的README文档。

3. 准备迁移执行机

   参考https://gitcode.com/opengauss/openGauss-workbench/blob/master/plugins/data-migration/README.md文档。

注：由于数据迁移功能较为复杂，使用MCP进行数据迁移前，建议先通过DataKit的Web页面熟悉迁移业务流程和操作。

## MCP服务搭建

1. 下载代码

   将当前MigrationMcp项目中的代码下载到一个openEuler的Linux环境中，并在此Linux服务器中准备JDK21环境和maven3.8+环境，注意配置好环境变量。

2. 打开项目

   使用VSCode远程连接第一步的Linux服务器，并打开MigrationMcp项目。

3. 配置DataKit服务信息

   修改文件项目中的`src/main/resources/application.properties`文件，配置其中的DataKit服务相关内容，其他配置项请勿修改。

   根据**环境准备**搭建的DataKit服务配置如下内容：

   ```properties
   # Your DataKit server information
   datakit.url=https://localhost:9494
   datakit.user=admin
   datakit.password=your_password
   ```

4. 打包项目

   在项目目录下，使用`mvn clean package -DskipTests`命令对项目进行打包，打包成功后可以在项目目录下看到如下文件`target/MigrationMcp-0.0.1-SNAPSHOT.jar`。

5. 配置MCP服务

   在VSCode中下载`Roo Code`插件，并配置DeepSeek-V3的API。然后修改项目目录下的`.roo/mcp.json`文件，文件内容如下：

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
           "源端数据库集群列表",
           "创建数据迁移任务",
           "目标端数据库包含的database列表",
           "数据迁移任务列表",
           "源端数据库包含的database列表",
           "目标端数据库列表",
           "启动数据迁移任务",
           "源端数据库列表"
         ]
       }
     }
   }
   ```
   
   注意：如果使用java命令报错`MCP error -32000: Connection closed`，请将java命令修改为java的绝对路径后，尝试重启mcp服务。

6. MCP服务检查

   上述配置完成后，可以在`Roo Code`插件的**MCP服务管理**中看到`migration-mcp`正确加载，且状态正常，**工具**页签中可以看到此MCP服务支持的功能。

## MCP服务使用指引

你可以尝试使用类似如下指令，访问MCP服务，并启动数据迁移任务。

1. 请问我给如何创建并启动一个数据迁移任务。
2. 请问帮我列出所有的源端数据库和目标端数据库。
3. 请帮我查询在127.0.0.1:3306的数据库中有哪些database。
4. 请使用127.0.0.1:3306的source_db和127.0.0.1:5432的target_db创建一个迁移任务。
5. 请帮我启动上一步创建的迁移任务。

## 注意事项

1. 本项目仅为DataKIt数据迁移适配MCP服务的demo，目前仅支持**工具**页签中提供的功能，如迁移进度查看等功能，还需要使用DataKit的Web页面查看。
2. MCP服务启动前，需要先启动DataKit，否则MCP服务会启动失败。
3. 由于功能有限，需要通过DataKit的原有Web页面，完成源端数据源和目标端数据源的添加工作，并完成迁移执行机的准备工作。
4. 打包完成后，请勿修改DataKit服务端口或用户密码等信息，避免MCP服务无法正常连接DataKit服务的问题。