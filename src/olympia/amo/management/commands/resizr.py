import os

from django.core.management.base import BaseCommand
from django.template.defaultfilters import filesizeformat

from olympia.amo.utils import resize_image


def rrresize_image(*arg, **kwargs):
    return tuple((0, 0), (0, 0), 0)


class Command(BaseCommand):

    OPEN_HTML = """
    <html>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
        <style>
        html {
            font-family: sans-serif;
        }
        body {
            margin: 5px;
        }
        h1 {
            font-size: 150%;
            text-align: center;
        }
        img {
            display: inline-block;
            height: 200px;
            margin: 0 10px;
            width: 320px;
            object-fit: contain;
        }
        table, td {
            border: 2px solid #E9E9E9;
            border-collapse: collapse;
            padding: 5px;
        }
        td {
            text-align: center;
        }
        </style>
        <body>
          <table>
          <thead>
            <tr>
                <th>Dimensions</th>
                <th>Current (640x480) PNG</th>
                <th>Optimal size (533x400) PNG</th>
                <th>Optimal size (533x400) JPG quality:90</th>
                <th>Optimal size (533x400) JPG quality:80</th>
                <th>Optimal size (533x400) JPG quality:35</th>
            </tr>
          </thead>
          <tbody>
    """

    SIZES = [
        (640, 480, 'png', 0),
        (533, 400, 'png', 0),
        # (267, 200, 'png', 0),
        (533, 400, 'jpg', 90),
        (533, 400, 'jpg', 80),
        # (267, 200, 'jpg', 80),
        (533, 400, 'jpg', 35),
    ]

    def resize(self, base):
        src_parent = os.path.join(base, 'full')

        def do_resize_image(entry, width, height, format, quality):
            name = f'{os.path.splitext(entry.name)[0]}.{format}'
            full_path = os.path.join(base, f'{height}{format}-{quality}', name)
            _, original_size, colors = resize_image(
                entry.path,
                full_path,
                (width, height),
                format=format,
                quality=quality)
            filesize = os.path.getsize(full_path)
            return (f'{height}{format}-{quality}/{name}', filesize), original_size, colors

        rows = []
        with os.scandir(src_parent) as parent:
            for entry in parent:
                row = []
                if entry.is_file():
                    # print(entry.name)
                    original_size = None
                    for (width, height, format, quality) in self.SIZES:
                        data, original_size, colors = do_resize_image(
                            entry, width, height, format, quality)
                        row.append(data)
                    row = [(f'full/{entry.name}', original_size, colors), *row]
                rows.append(row)
        return rows

    def handle(self, *args, **options):
        base = os.path.join(os.getcwd(), 'screenshots')
        print("starting")
        rows = self.resize(base)
        # print(rows)
        with open('extension_preview_comparison.html', 'w') as out:
            out.write(self.OPEN_HTML)
            for row in rows:
                (full, *rest_of_row) = row
                html = (
                    '<tr>'
                    + f'<td>full: {full[1][0]}x{full[1][1]}<br>colors: {full[2] or ">256"}</td>'
                    + ''.join(
                        f'<td><img src="screenshots/{img}"><br/>'
                        f'{filesizeformat(size)}</td>'
                        for img, size in rest_of_row)
                    + '</tr>')
                out.write(html)
            out.write('</tbody></table></body></html>')
        print("done")
