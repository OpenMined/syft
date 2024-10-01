import textwrap
from collections.abc import Callable
from dataclasses import dataclass

from .client_config import ClientConfig
from .jsonable import Jsonable
from .link import SyftLink


@dataclass
class Code(Jsonable):
    name: str
    func_name: str
    syft_link: SyftLink | None = None
    readme_link: SyftLink | None = None
    requirements_link: SyftLink | None = None
    requirements: dict[str, str] | None = None
    _func: Callable | None = None
    _client_config: ClientConfig | None = None

    def _repr_html_(self):
        import pandas as pd

        output = f"<strong>{self.name}</strong>\n"
        table_data = {
            "Attribute": ["Name", "Syft Link", "Readme", "Requirements"],
            "Value": [
                self.name,
                "..." + str(self.syft_link)[-20:],
                "..." + str(self.readme_link)[-20:],
                "..." + str(self.requirements_link)[-20:],
            ],
        }

        # Create a DataFrame from the transposed data
        df = pd.DataFrame(table_data)
        if self._client_config:
            readme = self._client_config.resolve_link(self.readme_link)
            with open(readme) as f:
                output += "\nREADME:\n" + markdown_to_html(f.read()) + "\n"

        return output + df._repr_html_()

    # can also do from df where you specify the destination
    @classmethod
    def from_func(self, func: Callable):
        name = func.__name__
        code = Code(func_name=name, _func=func, name=name)
        # code.write_files(manifest)
        return code

    def get_function_source(self, func):
        source_code = inspect.getsource(func)
        dedented_code = textwrap.dedent(source_code)
        dedented_code = dedented_code.strip()
        decorator = "@syftbox_code"
        if dedented_code.startswith(decorator):
            dedented_code = dedented_code[len(decorator) :]
        return dedented_code

    @property
    def import_string(self) -> str:
        string = "from syftbox.lib."
        string += create_datasite_import_path(self.syft_link.datasite)  # a.at.b.com
        string += ".code import "
        string += self.clean_name
        return string

    def readme_template(self) -> str:
        readme = f"""
        # {self.name}

        Code:

        ## Import Syntax
        client_config.use()
        {self.import_string}

        ## Python Usage Example
        result = {self.func_name}()
        """
        return textwrap.dedent(readme)

    def __call__(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    @property
    def raw_code(self) -> str:
        if self._func:
            return self.get_function_source(self._func)

        code = ""
        if self._client_config:
            code_link = self._client_config.resolve_link(self.syft_link)
            with open(code_link) as f:
                code = f.read()
        return code

    @property
    def code(self):
        from IPython.display import Markdown

        return Markdown(f"```python\n{self.raw_code}\n```")

    def run(self, *args, resolve_private: bool = False, **kwargs):
        # todo figure out how to override sy_path in the sub code
        if self._client_config:
            code = self.raw_code

            # Evaluate the code and store the function in memory
            local_vars = {}
            exec(code, {}, local_vars)

            # Get the function name
            function_name = f"{self.clean_name}"
            if function_name not in local_vars:
                raise ValueError(
                    f"Function {function_name} not found in the loader code."
                )

            # Get the function from the local_vars
            inner_function = local_vars[function_name]

            return inner_function(*args, **kwargs)
        else:
            raise Exception("run client_config.use()")

    @classmethod
    def extract_imports(cls, source_code):
        imports = set()
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module.split(".")[0])
        return imports

    @property
    def clean_name(self) -> str:
        return to_safe_function_name(self.name)

    def write_files(self, manifest) -> bool:
        code_dir = Path(manifest.root_dir / "code" / self.clean_name)
        os.makedirs(code_dir, exist_ok=True)

        manifest.create_public_folder(code_dir)

        # write code
        code_path = code_dir / (self.clean_name + ".py")
        source = self.get_function_source(self._func)
        with open(code_path, "w") as f:
            f.write(source)
        self.syft_link = SyftLink.from_path(code_path)

        # write readme
        readme_link = code_dir / "README.md"
        with open(readme_link, "w") as f:
            f.write(self.readme_template())
        self.readme_link = SyftLink.from_path(readme_link)

        # write requirements.txt
        imports = self.extract_imports(source)
        requirements = {}

        installed_packages = {pkg.key: pkg.version for pkg in pkg_resources.working_set}
        requirements_txt_path = code_dir / "requirements.txt"
        with open(requirements_txt_path, "w") as f:
            for package in imports:
                if package in installed_packages:
                    requirements[package] = installed_packages[package]
                    f.write(f"{package}=={installed_packages[package]}\n")
                else:
                    requirements[package] = ""
                    f.write(f"{package}\n")
                    print(
                        f"Warning: {package} is not installed in the current environment."
                    )
        self.requirements_link = SyftLink.from_path(requirements_txt_path)
        self.requirements = requirements

    def publish(self, manifest: DatasiteManifest, overwrite: bool = False):
        if self.name in manifest.code and not overwrite:
            raise Exception(f"Code: {self.name} already in manifest")
        self.write_files(manifest)
        manifest.code[self.name] = self.to_dict()
        manifest.save(manifest.file_path)
        print("✅ Code Published")

    @property
    def file_path(self):
        if self._client_config:
            return self._client_config.resolve_link(self.syft_link)

    def to_flow(
        self,
        client_config,
        inputs=None,
        output=None,
        template="python",
        path=None,
        write_back_approved_path: str | None = None,
        write_back_denied_path: str | None = None,
    ) -> str:
        if path is None:
            path = Path(client_config.sync_folder) / "staging"
            os.makedirs(path, exist_ok=True)
        if output is None:
            output = {}

        if "name" not in output:
            output["name"] = "result"
        if "format" not in output:
            output["format"] = "json"

        values = list(inputs.values())

        first_value = values[0]

        if isinstance(first_value, list):
            emails = set([client_config.email])
            for dataset in first_value:
                their_email = dataset.syft_link.datasite
                emails.add(their_email)

            if "permission" not in output:
                perm = SyftPermission(
                    admin=list(emails),
                    read=list(emails),
                    write=list(emails),
                )
                output["permission"] = perm
        else:
            their_email = first_value.syft_link.datasite
            if "permission" not in output:
                perm = SyftPermission.theirs_with_my_read_write(
                    their_email=their_email, my_email=client_config.email
                )
                output["permission"] = perm

        # create folders
        init_flow(client_config, path, self.name, inputs, output, template)
        # save main.py
        main_code = create_main_py(client_config, inputs, output, self)

        flow_dir = Path(os.path.abspath(f"{path}/{self.name}"))

        main_code_path = flow_dir / "main.py"
        with open(main_code_path, "w") as f:
            f.write(main_code)
        main_shell_path = flow_dir / "run.sh"
        main_shell_code = make_run_sh()
        with open(main_shell_path, "w") as f:
            f.write(main_shell_code)
        make_executable(main_shell_path)

        if write_back_approved_path is None:
            write_back_approved_path = "results/2_approved"

        if write_back_denied_path is None:
            write_back_denied_path = "results/3_denied"

        task_manifest = TaskManifest(
            author=client_config.email,
            result_datasite=client_config.email,
            execution_datasite=their_email,
            write_back_approved_path=write_back_approved_path,
            write_back_denied_path=write_back_denied_path,
        )

        task_manifest_path = flow_dir / "manifest.json"
        task_manifest.save(task_manifest_path)

        return str(flow_dir)
