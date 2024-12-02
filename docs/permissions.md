# Permissions

Users can define permissions for paths (files or folders) in their syftbox. Permissions define which other users can read, create, update or delete specific paths. Users can also invite other users to set permissions for specific paths.

## Format of a permission
Permissions are defined by creating a set of `.syftperm` files at several levels in your datasite. A `.syftperm` file can define permissions for all paths lower in the directory structure by defining a set of rules. An example of a such a set of rules in a .syftperm` file is:

```
- permission: read
  path: x.txt
  user: user@example.org
  type: allow
  terminal: false
  
- permission: read
  user: *
  type: allow
  terminal: false
```

## Rule arguments

Can be a specific user or {useremail}

### permission
A `permission` can have `read`, `create`, `write`

### user
Can be a specific user email, e.g. `user@example.org` or `*`

### path
A path is a unix style glob pattern. You can only use patterns for paths that are in the current directory or lower directory, not parent directories Currently its not supporting  It also accepts `{useremail}` as a value, which will resolve to a specific user. Valid examples of the `path` values are:   

- `*`: all paths in the current directory  
- `*.txt`: all txt files in the current directory  
- `*`




- types
    - effective permissions
        - read/create/update/update_permissions
        - these are store using bitwise independent permissions bits. Except for update_permissions, we have the admin bit.
            - read/create/update/admin
            - If you are admin, all checks are skipped when checking permissions
            - if you do not have the read bit, you also lose effect write/update
    - roles
        - roles are like aliases. They allow you to give multiple permissions with short syntax 
        - examples
            - admin -> implies admin
            - creator -> implies read+create
            - updater -> implies read+update
            - writer -> implies read+create+update
        - for disallowing, the usage pattern will probably be more fine grained, so you can use permissions like read/create
