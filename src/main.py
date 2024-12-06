from wox_plugin import Plugin, Context, PluginInitParams, Query, Result

class KillProcessPlugin(Plugin):
    async def init(self, ctx: Context, params: PluginInitParams) -> None:
        self.api = params.API
        
    async def query(self, ctx: Context, query: Query) -> list[Result]:
        return [
            Result(
                Title="Kill Process",
                SubTitle="Kill a process by name",
            )
        ]
    

plugin = KillProcessPlugin()