local ok, error_message = require('cudy.webfiles-storage').prepare('/etc/cudy-webfiles', 0)
if not ok then
    io.stderr:write('cudy-webfiles: ' .. error_message .. '\n')
    os.exit(1)
end
